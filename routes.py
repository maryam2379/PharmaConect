import secrets
import random
import os
import re
import requests as http_requests
import cv2
import numpy as np
from flask import Blueprint, render_template, request, redirect, url_for, flash, session, jsonify, current_app
from werkzeug.utils import secure_filename
from db import db
from models import User, Pharmacy, Medicine, Order, Stock, QRCode
from email_utils import send_email
from datetime import datetime, date
from pyzbar.pyzbar import decode
from qreader import QReader

main_bp = Blueprint('main', __name__)

# ------------------------------------------------------------------
# Parser GS1 — déchiffrage automatique des codes médicaments
# ------------------------------------------------------------------

# Application Identifiers GS1 avec leurs longueurs fixes (None = variable, terminé par  ou fin)
_GS1_AI_LENGTHS = {
    '00': 18, '01': 14, '02': 14,
    '10': None, '11': 6, '17': 6, '21': None,
    '30': None, '37': None,
    '240': None, '241': None, '310': 6, '311': 6,
    '400': None, '401': None, '410': 13, '411': 13,
    '412': 13, '413': 13, '414': 13,
    '8005': 6, '8012': None, '8020': None,
}

def parse_gs1(raw: str) -> dict:
    """
    Parse une chaîne GS1-128 / GS1 DataMatrix brute.
    Supporte les formats :
      - Avec parenthèses : (01)12345678901234(17)251231(10)LOT01
      - Sans parenthèses (flux brut) : 0112345678901234171231021001
      - Avec séparateur GS (\x1d) entre AIs variables
    Retourne un dict avec les clés nommées.
    """
    result = {}
    s = raw.strip()

    # Format avec parenthèses : (AI)valeur
    if '(' in s:
        pattern = re.compile(r'\((\d{2,4})\)([^(]*)')
        for m in pattern.finditer(s):
            ai, val = m.group(1), m.group(2).strip()
            result[ai] = val
    else:
        # Format flux brut — on avance caractère par caractère
        s = s.replace('\x1d', '\x1d')  # garder GS tel quel
        i = 0
        while i < len(s):
            # Identifier l'AI (2, 3 ou 4 chiffres)
            ai = None
            for length in (4, 3, 2):
                candidate = s[i:i+length]
                if candidate in _GS1_AI_LENGTHS:
                    ai = candidate
                    break
            if ai is None:
                break
            i += len(ai)
            fixed_len = _GS1_AI_LENGTHS[ai]
            if fixed_len is not None:
                result[ai] = s[i:i+fixed_len]
                i += fixed_len
            else:
                # Variable : lire jusqu'au séparateur GS ou fin
                end = s.find('\x1d', i)
                if end == -1:
                    result[ai] = s[i:]
                    break
                result[ai] = s[i:end]
                i = end + 1

    return result


def _parse_expiry(yymmdd: str):
    """Convertit YYMMDD en objet date. DD=00 → dernier jour du mois."""
    try:
        yy = int(yymmdd[0:2])
        mm = int(yymmdd[2:4])
        dd = int(yymmdd[4:6])
        year = 2000 + yy if yy < 50 else 1900 + yy
        if dd == 0:
            import calendar
            dd = calendar.monthrange(year, mm)[1]
        return date(year, mm, dd)
    except Exception:
        return None


def _lookup_gtin(gtin: str) -> dict:
    """
    Cherche les infos produit par GTIN via Open Food Facts (médicaments OTC)
    puis fallback Open Drug Data (RxNorm / openFDA).
    Retourne un dict partiel avec les champs disponibles.
    """
    info = {}

    # 1. Open Food Facts (produits grand public, médicaments OTC)
    try:
        url = f"https://world.openfoodfacts.org/api/v0/product/{gtin}.json"
        resp = http_requests.get(url, timeout=5)
        if resp.status_code == 200:
            data = resp.json()
            if data.get('status') == 1:
                prod = data.get('product', {})
                info['name'] = prod.get('product_name') or prod.get('generic_name') or ''
                info['manufacturer'] = prod.get('brands') or prod.get('manufacturer') or ''
                info['generic_name'] = prod.get('generic_name') or ''
                info['form'] = prod.get('categories') or ''
    except Exception:
        pass

    # 2. OpenFDA — médicaments
    if not info.get('name'):
        try:
            url = f"https://api.fda.gov/drug/ndc.json?search=product_ndc:{gtin}&limit=1"
            resp = http_requests.get(url, timeout=5)
            if resp.status_code == 200:
                data = resp.json()
                results = data.get('results', [])
                if results:
                    r = results[0]
                    info['name'] = r.get('brand_name') or r.get('generic_name') or ''
                    info['generic_name'] = r.get('generic_name') or ''
                    info['manufacturer'] = r.get('labeler_name') or ''
                    info['dosage'] = r.get('dosage_form') or ''
                    info['form'] = r.get('dosage_form') or ''
                    info['prescription_required'] = r.get('marketing_category', '').upper() not in ('OTC', 'OTCMONOGRAPH')
        except Exception:
            pass

    return info


def decode_medicine_from_code(raw_code: str) -> dict:
    """
    Point d'entrée unique : reçoit un code brut (QR, barcode, DataMatrix).
    Retourne un dict structuré avec tous les champs disponibles pour Medicine + Stock.

    Stratégies dans l'ordre :
      1. Format interne custom  name|generic|manufacturer|dosage|form|expiry|lot
      2. Format JSON {"name":..., "dosage":...}
      3. GS1 standard (parenthèses ou flux brut)
      4. Code numérique seul → traité comme GTIN (lookup API)
    """
    info = {
        'raw_code': raw_code,
        'name': '',
        'generic_name': '',
        'manufacturer': '',
        'dosage': '',
        'form': '',
        'prescription_required': False,
        'expiry_date': None,
        'batch_number': '',
        'serial_number': '',
        'gtin': '',
        'source': 'unknown',
    }

    s = raw_code.strip()

    # --- Stratégie 1 : Format JSON ---
    if s.startswith('{'):
        try:
            import json
            d = json.loads(s)
            info.update({k: v for k, v in d.items() if k in info})
            info['source'] = 'json'
            return info
        except Exception:
            pass

    # --- Stratégie 2 : Format pipe custom name|generic|manufacturer|dosage|form|expiry|lot ---
    if '|' in s and not s.startswith('(') and not re.match(r'^\d{8,}', s):
        parts = s.split('|')
        fields = ['name', 'generic_name', 'manufacturer', 'dosage', 'form', 'expiry_date', 'batch_number']
        for idx, field in enumerate(fields):
            if idx < len(parts) and parts[idx]:
                if field == 'expiry_date':
                    # Accepter YYYY-MM-DD ou YYMMDD
                    val = parts[idx].strip()
                    if re.match(r'^\d{4}-\d{2}-\d{2}$', val):
                        try:
                            info['expiry_date'] = datetime.strptime(val, '%Y-%m-%d').date()
                        except Exception:
                            pass
                    elif re.match(r'^\d{6}$', val):
                        info['expiry_date'] = _parse_expiry(val)
                else:
                    info[field] = parts[idx].strip()
        info['source'] = 'pipe'
        return info

    # --- Stratégie 3 : GS1 (parenthèses ou flux brut numérique) ---
    gs1 = {}
    if '(' in s or re.match(r'^[\d\x1d]+', s):
        gs1 = parse_gs1(s)

    if gs1:
        gtin = gs1.get('01', '')
        info['gtin'] = gtin
        info['batch_number'] = gs1.get('10', '')
        info['serial_number'] = gs1.get('21', '')
        expiry_raw = gs1.get('17', '')
        if expiry_raw:
            info['expiry_date'] = _parse_expiry(expiry_raw)

        # Lookup GTIN pour enrichir name/manufacturer
        if gtin:
            enriched = _lookup_gtin(gtin)
            for k, v in enriched.items():
                if v:
                    info[k] = v

        # Si le nom reste vide, utiliser le GTIN comme nom temporaire
        if not info['name'] and gtin:
            info['name'] = f"GTIN-{gtin}"

        info['source'] = 'gs1'
        return info

    # --- Stratégie 4 : Code numérique seul (GTIN EAN-8/13/14) ---
    if re.match(r'^\d{8,14}$', s):
        info['gtin'] = s
        info['batch_number'] = s
        enriched = _lookup_gtin(s)
        for k, v in enriched.items():
            if v:
                info[k] = v
        if not info['name']:
            info['name'] = f"GTIN-{s}"
        info['source'] = 'gtin'
        return info

    # --- Fallback : code opaque, utiliser comme nom ---
    info['name'] = s[:150]
    info['batch_number'] = s
    info['source'] = 'raw'
    return info


UPLOAD_FOLDER = 'uploads'
ALLOWED_EXTENSIONS = {'pdf', 'png', 'jpg', 'jpeg'}
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# Initialisation de QReader (instance unique)
_qreader_instance = None

def get_qreader():
    global _qreader_instance
    if _qreader_instance is None:
        _qreader_instance = QReader()
    return _qreader_instance

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

# ------------------------------------------------------------------
# Fonctions d'envoi d'emails
# ------------------------------------------------------------------
def send_verification_email(user):
    token = user.verification_token
    link = url_for('main.verify_email', token=token, _external=True)
    subject = "Vérifiez votre compte MediTrack Cameroun"
    body = f"Bonjour {user.full_name},\n\nCliquez sur le lien suivant pour vérifier votre compte :\n{link}\n\nCe lien expire dans 24 heures.\n\nL'équipe MediTrack"
    return send_email(user.email, subject, body)

def send_otp_email(user):
    otp = user.otp_code
    subject = "Code OTP MediTrack Cameroun"
    body = f"Bonjour {user.full_name},\n\nVotre code de vérification est : {otp}\n\nCe code expire dans 15 minutes.\n\nCordialement,\nMediTrack Cameroun"
    return send_email(user.email, subject, body)

# ------------------------------------------------------------------
# Routes publiques
# ------------------------------------------------------------------
@main_bp.route("/")
def home():
    return render_template("index.html")

@main_bp.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "GET":
        return render_template("auth/register.html")

    if request.is_json:
        data = request.get_json()
        role = data.get('role')
        email = data.get('email')
        password = data.get('password')
        profile_data = data.get('profile_data', {})
        uploaded_docs = data.get('documents', {})

        if not email or not password or not role:
            return jsonify({'success': False, 'message': 'Champs obligatoires manquants'}), 400

        existing = User.query.filter_by(email=email).first()
        if existing:
            return jsonify({'success': False, 'message': 'Email déjà utilisé'}), 400

        prenom = profile_data.get('prenom', '')
        nom = profile_data.get('nom', '')
        full_name = f"{prenom} {nom}".strip()
        phone = profile_data.get('telephone', '')

        new_user = User(
            email=email,
            phone=phone,
            full_name=full_name or email.split('@')[0],
            role=role,
            is_active=False,
            is_verified=False,
            verification_token=secrets.token_urlsafe(32),
            otp_code=f"{random.randint(100000, 999999)}",
            documents=uploaded_docs
        )
        new_user.set_password(password)
        db.session.add(new_user)
        db.session.flush()

        if role == 'pharmacien':
            pharmacy = Pharmacy(
                name=profile_data.get('nomPharmacie', ''),
                license_number=profile_data.get('ordreOnpc', ''),
                address=profile_data.get('geoInput', ''),
                city=profile_data.get('region', ''),
                phone=phone,
                email=email,
                manager_id=new_user.id,
                is_verified=False
            )
            db.session.add(pharmacy)

        db.session.commit()
        send_verification_email(new_user)

        upgrade_id = f"UPGRADE-CM-{new_user.id:06d}"
        return jsonify({
            'success': True,
            'upgrade_id': upgrade_id,
            'email': new_user.email,
            'message': 'Inscription réussie. Vérifiez votre boîte email.'
        })

    else:
        # Formulaire classique (compatibilité)
        email = request.form.get("email")
        phone = request.form.get("phone")
        full_name = request.form.get("full_name")
        password = request.form.get("password")
        role = request.form.get("role")

        existing = User.query.filter((User.email == email) | (User.phone == phone)).first()
        if existing:
            flash("Un compte avec cet email ou téléphone existe déjà.", "danger")
            return redirect(url_for("main.register"))

        new_user = User(
            email=email,
            phone=phone,
            full_name=full_name,
            role=role,
            is_active=False,
            is_verified=False,
            verification_token=secrets.token_urlsafe(32),
            otp_code=f"{random.randint(100000, 999999)}"
        )
        new_user.set_password(password)
        db.session.add(new_user)
        db.session.flush()

        if role == "pharmacien":
            pharmacy = Pharmacy(
                name=request.form.get("pharmacy_name"),
                license_number=request.form.get("license_number"),
                address=request.form.get("pharmacy_address"),
                city=request.form.get("pharmacy_city"),
                phone=request.form.get("pharmacy_phone"),
                email=request.form.get("pharmacy_email"),
                manager_id=new_user.id,
                is_verified=False
            )
            db.session.add(pharmacy)

        db.session.commit()
        session['pending_user_id'] = new_user.id
        return redirect(url_for("main.verification_choice"))

@main_bp.route("/upload-document", methods=["POST"])
def upload_document():
    if 'document' not in request.files:
        return jsonify({'success': False, 'message': 'Aucun fichier'}), 400
    file = request.files['document']
    doc_type = request.form.get('type', 'unknown')
    if file.filename == '':
        return jsonify({'success': False, 'message': 'Nom vide'}), 400
    if not allowed_file(file.filename):
        return jsonify({'success': False, 'message': 'Type non autorisé (PDF, JPG, PNG)'}), 400

    filename = secure_filename(f"{doc_type}_{file.filename}")
    filepath = os.path.join(UPLOAD_FOLDER, filename)
    file.save(filepath)

    return jsonify({
        'success': True,
        'path': filepath,
        'name': filename,
        'size': os.path.getsize(filepath)
    })

@main_bp.route("/verification-choice")
def verification_choice():
    if 'pending_user_id' not in session:
        return redirect(url_for("main.register"))
    return render_template("auth/verification_choice.html")

@main_bp.route("/send-otp")
def send_otp_route():
    user_id = session.get('pending_user_id')
    if not user_id:
        return redirect(url_for("main.register"))
    user = User.query.get(user_id)
    if user:
        if send_otp_email(user):
            flash("Un code OTP a été envoyé à votre adresse email.", "info")
        else:
            flash("Erreur lors de l'envoi du code. Réessayez plus tard.", "danger")
    return redirect(url_for("main.verify_otp"))

@main_bp.route("/verify-otp", methods=["GET", "POST"])
def verify_otp():
    user_id = session.get('pending_user_id')
    if not user_id:
        return redirect(url_for("main.register"))
    user = User.query.get(user_id)
    if request.method == "POST":
        entered_otp = request.form.get("otp")
        if entered_otp == user.otp_code:
            user.is_active = True
            user.is_verified = True
            user.verification_token = None
            user.otp_code = None
            db.session.commit()
            session.pop('pending_user_id', None)
            flash("Votre compte a été vérifié avec succès ! Vous pouvez vous connecter.", "success")
            return redirect(url_for("main.login"))
        else:
            flash("Code OTP invalide.", "danger")
    return render_template("auth/verify_otp.html", email=user.email)

@main_bp.route("/send-verification-link")
def send_verification_link():
    user_id = session.get('pending_user_id')
    if not user_id:
        return redirect(url_for("main.register"))
    user = User.query.get(user_id)
    if user:
        if send_verification_email(user):
            flash("Un lien de vérification a été envoyé à votre adresse email.", "info")
        else:
            flash("Erreur d'envoi. Réessayez plus tard.", "danger")
    return redirect(url_for("main.verification_choice"))

@main_bp.route("/verify-email/<token>")
def verify_email(token):
    user = User.query.filter_by(verification_token=token).first()
    if user:
        user.is_active = True
        user.is_verified = True
        user.verification_token = None
        user.otp_code = None
        db.session.commit()
        session.pop('pending_user_id', None)
        flash("Votre adresse email a été vérifiée. Vous pouvez maintenant vous connecter.", "success")
        return redirect(url_for("main.login"))
    else:
        flash("Lien de vérification invalide ou expiré.", "danger")
        return redirect(url_for("main.register"))

# ------------------------------------------------------------------
# Routes d'authentification (connexion / déconnexion)
# ------------------------------------------------------------------
@main_bp.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "GET":
        return render_template("auth/login.html")
    
    email = request.form.get("email")
    password = request.form.get("password")
    remember = request.form.get("remember") == "on"
    
    if not email or not password:
        flash("Veuillez remplir tous les champs.", "danger")
        return redirect(url_for("main.login"))
    
    user = User.query.filter_by(email=email).first()
    
    if not user or not user.check_password(password):
        flash("Email ou mot de passe incorrect.", "danger")
        return redirect(url_for("main.login"))
    
    if not user.is_verified:
        flash("Votre compte n'est pas encore vérifié. Vérifiez votre boîte email.", "warning")
        return redirect(url_for("main.login"))
    
    if not user.is_active:
        flash("Votre compte est désactivé. Contactez l'administrateur.", "danger")
        return redirect(url_for("main.login"))
    
    session.permanent = remember
    session['user_id'] = user.id
    session['role'] = user.role
    session['full_name'] = user.full_name
    session['email'] = user.email
    
    flash(f"Bienvenue {user.full_name} !", "success")
    return redirect(url_for("main.dashboard"))

@main_bp.route("/logout")
def logout():
    session.clear()
    flash("Vous avez été déconnecté avec succès.", "info")
    return redirect(url_for("main.home"))

# ------------------------------------------------------------------
# Dashboards (protégés par rôle)
# ------------------------------------------------------------------
@main_bp.route("/dashboard")
def dashboard():
    if 'user_id' not in session:
        flash("Veuillez vous connecter.", "warning")
        return redirect(url_for("main.login"))

    user = User.query.get(session['user_id'])
    role = session.get('role')

    stats = {}
    recent_searches = []
    critical_stock = []
    recent_users = []
    pending_pharmacies = []
    recent_orders = []

    if role == 'patient':
        stats['recent_searches'] = 0
        stats['scans'] = 0
        stats['nearby_pharmacies'] = 0
    elif role == 'pharmacien':
        stats['total_stock'] = 0
        stats['low_stock'] = 0
        stats['pending_orders'] = 0
    elif role == 'admin':
        stats['users'] = User.query.count()
        stats['pharmacies'] = Pharmacy.query.count()
        stats['medicines'] = Medicine.query.count()
        stats['orders'] = Order.query.count()
        recent_users = User.query.order_by(User.id.desc()).limit(5).all()
        pending_pharmacies = Pharmacy.query.filter_by(is_verified=False).all()
    elif role == 'grossiste':
        stats['supplier_orders'] = 0
        stats['deliveries'] = 0
        stats['revenue'] = "0 FCFA"

    return render_template("admin/dashboard.html",
                           user=user,
                           stats=stats,
                           recent_searches=recent_searches,
                           critical_stock=critical_stock,
                           recent_users=recent_users,
                           pending_pharmacies=pending_pharmacies,
                           recent_orders=recent_orders)

# ------------------------------------------------------------------
# Pages publiques
# ------------------------------------------------------------------
@main_bp.route("/anti-counterfeit")
def anti_counterfeit():
    return render_template("anti_counterfeit.html")

@main_bp.route("/pharmacies")
def pharmacies():
    return render_template("pharmacies.html")

@main_bp.route("/faq")
def faq():
    return render_template("layout/faq.html")

# ------------------------------------------------------------------
# Profil utilisateur
# ------------------------------------------------------------------
@main_bp.route("/profile", methods=["GET", "POST"])
def profile():
    if 'user_id' not in session:
        flash("Veuillez vous connecter.", "warning")
        return redirect(url_for("main.login"))
    
    user = User.query.get(session['user_id'])
    if not user:
        session.clear()
        flash("Utilisateur introuvable.", "danger")
        return redirect(url_for("main.login"))
    
    pharmacy = None
    if user.role == 'pharmacien':
        pharmacy = Pharmacy.query.filter_by(manager_id=user.id).first()
    
    if request.method == "POST":
        form_type = request.form.get("form_type")
        
        if form_type == "user":
            full_name = request.form.get("full_name", "").strip()
            email = request.form.get("email", "").strip()
            phone = request.form.get("phone", "").strip()
            if email != user.email:
                if User.query.filter(User.email == email, User.id != user.id).first():
                    flash("Cet email est déjà utilisé.", "danger")
                    return redirect(url_for("main.profile"))
            user.full_name = full_name
            user.email = email
            user.phone = phone
            
            old = request.form.get("old_password")
            new = request.form.get("new_password")
            confirm = request.form.get("confirm_password")
            if old and new and confirm:
                if not user.check_password(old):
                    flash("Ancien mot de passe incorrect.", "danger")
                    return redirect(url_for("main.profile"))
                if new != confirm:
                    flash("Les mots de passe ne correspondent pas.", "danger")
                    return redirect(url_for("main.profile"))
                if len(new) < 6:
                    flash("Mot de passe trop court (min 6).", "danger")
                    return redirect(url_for("main.profile"))
                user.set_password(new)
                flash("Mot de passe mis à jour.", "success")
            db.session.commit()
            session['full_name'] = user.full_name
            flash("Informations personnelles mises à jour.", "success")
        
        elif form_type == "pharmacy" and pharmacy:
            pharmacy.name = request.form.get("pharmacy_name", "").strip()
            pharmacy.license_number = request.form.get("license_number", "").strip()
            pharmacy.address = request.form.get("address", "").strip()
            pharmacy.city = request.form.get("city", "").strip()
            pharmacy.phone = request.form.get("pharmacy_phone", "").strip()
            pharmacy.email = request.form.get("pharmacy_email", "").strip()
            db.session.commit()
            flash("Informations de la pharmacie mises à jour.", "success")
        
        elif form_type == "preferences":
            flash("Préférences enregistrées (démonstration).", "success")
        
        return redirect(url_for("main.profile"))
    
    return render_template("admin/profile.html", user=user, pharmacy=pharmacy)

# ------------------------------------------------------------------
# API Scan et upload QR code (avec amélioration QReader)
# ------------------------------------------------------------------
@main_bp.route("/scan")
def scan_page():
    if 'user_id' not in session:
        flash("Veuillez vous connecter.", "warning")
        return redirect(url_for("main.login"))
    return render_template("admin/scan.html")

@main_bp.route("/api/scan", methods=["POST"])
def api_scan():
    """
    Scan principal : verification anti-contrefacon + insertion automatique
    pour pharmaciens/admins si le code est inconnu.
    """
    if 'user_id' not in session:
        return jsonify({'success': False, 'message': 'Non authentifie'}), 401

    data = request.get_json()
    scanned_code = data.get('code', '').strip()
    if not scanned_code:
        return jsonify({'success': False, 'message': 'Code vide'}), 400

    user = User.query.get(session['user_id'])
    role = user.role

    # 1. Code deja connu en DB → verification anti-contrefacon
    qr = QRCode.query.filter_by(code=scanned_code).first()
    if qr:
        medicine = qr.medicine
        if qr.status == 'used' and role != 'pharmacien':
            return jsonify({
                'success': False,
                'message': '⚠️ Ce médicament a déjà été scanné ! Possible contrefaçon.'
            })
        if role == 'patient' and qr.status == 'active':
            qr.status = 'used'
            qr.verified_at = datetime.utcnow()
            qr.verified_by = 'patient'
            db.session.commit()
        return jsonify({
            'success': True,
            'already_known': True,
            'medicine': {
                'id': medicine.id,
                'name': medicine.name,
                'generic_name': medicine.generic_name,
                'manufacturer': medicine.manufacturer,
                'dosage': medicine.dosage,
                'form': medicine.form,
                'prescription_required': medicine.prescription_required,
                'authentic': qr.status == 'used' if role == 'patient' else True
            }
        })

    # 2. Code inconnu → dechiffrage automatique
    decoded = decode_medicine_from_code(scanned_code)

    # Pour les patients : signaler que le medicament est inconnu
    if role == 'patient':
        return jsonify({
            'success': False,
            'not_found': True,
            'message': 'Médicament non trouvé dans la base. Consultez un pharmacien.'
        }), 404

    # 3. Insertion automatique (pharmacien / admin)
    try:
        med_info = decoded
        pharmacy = None

        # Chercher ou creer le medicament
        medicine = None
        if med_info.get('gtin'):
            existing_qr = QRCode.query.filter(
                QRCode.serial_number == med_info['gtin']
            ).first()
            if existing_qr:
                medicine = existing_qr.medicine

        if not medicine and med_info.get('name') and not med_info['name'].startswith('GTIN-'):
            medicine = Medicine.query.filter_by(
                name=med_info['name'],
                dosage=med_info.get('dosage', '')
            ).first()

        if not medicine:
            medicine = Medicine(
                name=med_info.get('name') or f'Medicament-{scanned_code[:20]}',
                generic_name=med_info.get('generic_name', ''),
                manufacturer=med_info.get('manufacturer', ''),
                dosage=med_info.get('dosage', ''),
                form=med_info.get('form', ''),
                prescription_required=bool(med_info.get('prescription_required', False)),
            )
            db.session.add(medicine)
            db.session.flush()
            is_new_medicine = True
        else:
            is_new_medicine = False

        # Gerer le stock si pharmacien
        stock_id = None
        if role == 'pharmacien':
            pharmacy = Pharmacy.query.filter_by(manager_id=user.id).first()
            if pharmacy:
                from datetime import timedelta
                expiry = med_info.get('expiry_date')
                if not expiry:
                    expiry = (datetime.utcnow() + timedelta(days=365)).date()

                batch = med_info.get('batch_number', '')
                stock = Stock.query.filter_by(
                    pharmacy_id=pharmacy.id,
                    medicine_id=medicine.id,
                    batch_number=batch
                ).first()
                if stock:
                    stock.quantity += 1
                    stock.last_updated = datetime.utcnow()
                else:
                    stock = Stock(
                        pharmacy_id=pharmacy.id,
                        medicine_id=medicine.id,
                        quantity=1,
                        expiry_date=expiry,
                        price=0,
                        batch_number=batch
                    )
                    db.session.add(stock)
                    db.session.flush()
                stock_id = stock.id

        # Enregistrer le QRCode pour future detection
        if not QRCode.query.filter_by(code=scanned_code).first():
            qr_entry = QRCode(
                code=scanned_code,
                serial_number=med_info.get('serial_number') or med_info.get('gtin') or scanned_code,
                status='active',
                medicine_id=medicine.id,
                pharmacy_id=pharmacy.id if pharmacy else None
            )
            db.session.add(qr_entry)

        db.session.commit()

        expiry_val = med_info.get('expiry_date')
        return jsonify({
            'success': True,
            'auto_inserted': True,
            'is_new_medicine': is_new_medicine,
            'source': med_info.get('source', 'unknown'),
            'medicine': {
                'id': medicine.id,
                'name': medicine.name,
                'generic_name': medicine.generic_name,
                'manufacturer': medicine.manufacturer,
                'dosage': medicine.dosage,
                'form': medicine.form,
                'prescription_required': medicine.prescription_required,
                'authentic': True,
                'batch_number': med_info.get('batch_number', ''),
                'expiry_date': expiry_val.isoformat() if expiry_val else None,
                'gtin': med_info.get('gtin', ''),
            },
            'stock_id': stock_id,
            'message': (
                'Nouveau medicament cree et ajoute au stock automatiquement.'
                if is_new_medicine else
                'Stock mis a jour automatiquement.'
            )
        })

    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"[api_scan] Erreur insertion auto : {e}")
        return jsonify({
            'success': False,
            'message': f"Erreur insertion automatique : {str(e)}"
        }), 500

@main_bp.route("/api/upload-qrcode", methods=["POST"])
def api_upload_qrcode():
    """
    Reçoit une image, utilise QReader (robuste) pour extraire le QR code.
    Fallback sur pyzbar avec prétraitement.
    """
    if 'user_id' not in session:
        return jsonify({'success': False, 'message': 'Non authentifié'}), 401
    
    if 'image' not in request.files:
        return jsonify({'success': False, 'message': 'Aucune image fournie'}), 400
    
    file = request.files['image']
    if file.filename == '':
        return jsonify({'success': False, 'message': 'Fichier vide'}), 400
    
    try:
        img_bytes = file.read()
        np_arr = np.frombuffer(img_bytes, np.uint8)
        img = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)
        
        if img is None:
            return jsonify({'success': False, 'message': 'Image invalide'}), 400
        
        qr_data = None
        
        # 1. Tentative avec QReader (robuste)
        try:
            qreader = get_qreader()
            img_rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
            decoded_texts = qreader.detect_and_decode(image=img_rgb)
            if decoded_texts and decoded_texts[0] is not None:
                qr_data = decoded_texts[0]
                print(f"[QReader] Décodé : {qr_data}")
        except Exception as e:
            print(f"[QReader] Erreur : {e}")
        
        # 2. Fallback pyzbar avec prétraitement
        if qr_data is None:
            gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
            kernel = np.array([[-1,-1,-1], [-1,9,-1], [-1,-1,-1]])
            sharpened = cv2.filter2D(gray, -1, kernel)
            clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8,8))
            contrasted = clahe.apply(sharpened)
            decoded_objects = decode(contrasted)
            if decoded_objects:
                qr_data = decoded_objects[0].data.decode('utf-8')
                print(f"[pyzbar] Décodé : {qr_data}")
        
        if qr_data is None:
            return jsonify({'success': False, 'message': 'Aucun QR code trouvé dans l\'image'}), 404
        
        return jsonify({'success': True, 'code': qr_data})
    
    except Exception as e:
        print(f"Erreur décodage: {e}")
        return jsonify({'success': False, 'message': f'Erreur lors du décodage : {str(e)}'}), 500

@main_bp.route("/api/medicine/add", methods=["POST"])
def api_add_medicine():
    if 'user_id' not in session:
        return jsonify({'success': False, 'message': 'Non authentifié'}), 401
    
    user = User.query.get(session['user_id'])
    if user.role not in ['pharmacien', 'admin']:
        return jsonify({'success': False, 'message': 'Permission refusée'}), 403
    
    data = request.get_json()
    name = data.get('name', '').strip()
    generic_name = data.get('generic_name', '').strip()
    manufacturer = data.get('manufacturer', '').strip()
    dosage = data.get('dosage', '').strip()
    form = data.get('form', '').strip()
    prescription_required = data.get('prescription_required', False)
    barcode = data.get('barcode', '').strip()
    quantity = int(data.get('quantity', 0))
    expiry_date = data.get('expiry_date')
    price = float(data.get('price', 0))
    
    if not name:
        return jsonify({'success': False, 'message': 'Nom du médicament requis'}), 400
    
    # Vérifier si le médicament existe déjà
    existing = Medicine.query.filter_by(name=name, dosage=dosage, manufacturer=manufacturer).first()
    if not existing:
        medicine = Medicine(
            name=name,
            generic_name=generic_name,
            manufacturer=manufacturer,
            dosage=dosage,
            form=form,
            prescription_required=prescription_required
        )
        db.session.add(medicine)
        db.session.flush()
    else:
        medicine = existing
    
    if user.role == 'pharmacien':
        pharmacy = Pharmacy.query.filter_by(manager_id=user.id).first()
        if not pharmacy:
            return jsonify({'success': False, 'message': 'Aucune pharmacie associée'}), 400
        
        stock = Stock.query.filter_by(pharmacy_id=pharmacy.id, medicine_id=medicine.id).first()
        if stock:
            stock.quantity += quantity
            if expiry_date:
                stock.expiry_date = datetime.strptime(expiry_date, '%Y-%m-%d')
            stock.price = price
        else:
            stock = Stock(
                pharmacy_id=pharmacy.id,
                medicine_id=medicine.id,
                quantity=quantity,
                expiry_date=datetime.strptime(expiry_date, '%Y-%m-%d') if expiry_date else None,
                price=price,
                batch_number=data.get('batch_number', '')
            )
            db.session.add(stock)
    
    if barcode and not QRCode.query.filter_by(code=barcode).first():
        qr = QRCode(
            code=barcode,
            serial_number=barcode,
            status='active',
            medicine_id=medicine.id,
            pharmacy_id=pharmacy.id if user.role == 'pharmacien' else None
        )
        db.session.add(qr)
    
    db.session.commit()
    return jsonify({'success': True, 'message': 'Médicament ajouté avec succès', 'medicine_id': medicine.id})


# ------------------------------------------------------------------
# Gestion des stocks pour pharmacien (API)
# ------------------------------------------------------------------
@main_bp.route("/api/pharmacist/stocks", methods=["GET"])
def api_get_pharmacy_stocks():
    """Retourne tous les stocks de la pharmacie du pharmacien connecté."""
    if 'user_id' not in session:
        return jsonify({'success': False, 'message': 'Non authentifié'}), 401
    user = User.query.get(session['user_id'])
    if user.role != 'pharmacien':
        return jsonify({'success': False, 'message': 'Accès réservé aux pharmaciens'}), 403
    
    pharmacy = Pharmacy.query.filter_by(manager_id=user.id).first()
    if not pharmacy:
        return jsonify({'success': False, 'message': 'Aucune pharmacie associée'}), 404
    
    stocks = Stock.query.filter_by(pharmacy_id=pharmacy.id).all()
    result = []
    for stock in stocks:
        med = stock.medicine
        result.append({
            'id': stock.id,
            'medicine_id': med.id,
            'medicine': {
                'id': med.id,
                'name': med.name,
                'generic_name': med.generic_name,
                'manufacturer': med.manufacturer,
                'dosage': med.dosage,
                'form': med.form,
                'image_url': med.image_url or '/static/images/default-medicine.png',
                'prescription_required': med.prescription_required
            },
            'quantity': stock.quantity,
            'price': float(stock.price) if stock.price else 0,
            'batch_number': stock.batch_number,
            'expiry_date': stock.expiry_date.isoformat() if stock.expiry_date else None
        })
    return jsonify({'success': True, 'stocks': result})


@main_bp.route("/api/pharmacist/stock", methods=["POST"])
def api_create_stock():
    """Ajouter une nouvelle ligne de stock (liée à un médicament existant)."""
    if 'user_id' not in session:
        return jsonify({'success': False, 'message': 'Non authentifié'}), 401
    user = User.query.get(session['user_id'])
    if user.role != 'pharmacien':
        return jsonify({'success': False, 'message': 'Accès réservé aux pharmaciens'}), 403
    
    pharmacy = Pharmacy.query.filter_by(manager_id=user.id).first()
    if not pharmacy:
        return jsonify({'success': False, 'message': 'Aucune pharmacie associée'}), 404
    
    data = request.get_json()
    medicine_id = data.get('medicine_id')
    quantity = data.get('quantity')
    price = data.get('price')
    expiry_date_str = data.get('expiry_date')
    batch_number = data.get('batch_number', '')
    
    if not medicine_id or quantity is None or price is None or not expiry_date_str:
        return jsonify({'success': False, 'message': 'Champs obligatoires manquants'}), 400
    
    medicine = Medicine.query.get(medicine_id)
    if not medicine:
        return jsonify({'success': False, 'message': 'Médicament introuvable'}), 404
    
    try:
        expiry_date = datetime.strptime(expiry_date_str, '%Y-%m-%d').date()
    except:
        return jsonify({'success': False, 'message': 'Format de date invalide'}), 400
    
    stock = Stock(
        pharmacy_id=pharmacy.id,
        medicine_id=medicine_id,
        quantity=int(quantity),
        price=float(price),
        expiry_date=expiry_date,
        batch_number=batch_number
    )
    db.session.add(stock)
    db.session.commit()
    
    return jsonify({'success': True, 'message': 'Stock ajouté', 'stock_id': stock.id})


@main_bp.route("/api/pharmacist/stock/<int:stock_id>", methods=["PUT"])
def api_update_stock(stock_id):
    """Modifier une ligne de stock existante."""
    if 'user_id' not in session:
        return jsonify({'success': False, 'message': 'Non authentifié'}), 401
    user = User.query.get(session['user_id'])
    if user.role != 'pharmacien':
        return jsonify({'success': False, 'message': 'Accès réservé aux pharmaciens'}), 403
    
    pharmacy = Pharmacy.query.filter_by(manager_id=user.id).first()
    if not pharmacy:
        return jsonify({'success': False, 'message': 'Aucune pharmacie associée'}), 404
    
    stock = Stock.query.filter_by(id=stock_id, pharmacy_id=pharmacy.id).first()
    if not stock:
        return jsonify({'success': False, 'message': 'Stock introuvable'}), 404
    
    data = request.get_json()
    if 'quantity' in data:
        stock.quantity = int(data['quantity'])
    if 'price' in data:
        stock.price = float(data['price'])
    if 'expiry_date' in data:
        try:
            stock.expiry_date = datetime.strptime(data['expiry_date'], '%Y-%m-%d').date()
        except:
            pass
    if 'batch_number' in data:
        stock.batch_number = data['batch_number']
    if 'medicine_id' in data:
        # Vérifier que le médicament existe
        med = Medicine.query.get(data['medicine_id'])
        if med:
            stock.medicine_id = med.id
    
    db.session.commit()
    return jsonify({'success': True, 'message': 'Stock mis à jour'})


@main_bp.route("/api/pharmacist/stock/<int:stock_id>", methods=["DELETE"])
def api_delete_stock(stock_id):
    """Supprimer une ligne de stock."""
    if 'user_id' not in session:
        return jsonify({'success': False, 'message': 'Non authentifié'}), 401
    user = User.query.get(session['user_id'])
    if user.role != 'pharmacien':
        return jsonify({'success': False, 'message': 'Accès réservé aux pharmaciens'}), 403
    
    pharmacy = Pharmacy.query.filter_by(manager_id=user.id).first()
    if not pharmacy:
        return jsonify({'success': False, 'message': 'Aucune pharmacie associée'}), 404
    
    stock = Stock.query.filter_by(id=stock_id, pharmacy_id=pharmacy.id).first()
    if not stock:
        return jsonify({'success': False, 'message': 'Stock introuvable'}), 404
    
    db.session.delete(stock)
    db.session.commit()
    return jsonify({'success': True, 'message': 'Stock supprimé'})


@main_bp.route("/api/pharmacist/stock/<int:stock_id>/quantity", methods=["PATCH"])
def api_adjust_quantity(stock_id):
    """Ajuster rapidement la quantité d'un stock."""
    if 'user_id' not in session:
        return jsonify({'success': False, 'message': 'Non authentifié'}), 401
    user = User.query.get(session['user_id'])
    if user.role != 'pharmacien':
        return jsonify({'success': False, 'message': 'Accès réservé aux pharmaciens'}), 403
    
    pharmacy = Pharmacy.query.filter_by(manager_id=user.id).first()
    if not pharmacy:
        return jsonify({'success': False, 'message': 'Aucune pharmacie associée'}), 404
    
    stock = Stock.query.filter_by(id=stock_id, pharmacy_id=pharmacy.id).first()
    if not stock:
        return jsonify({'success': False, 'message': 'Stock introuvable'}), 404
    
    data = request.get_json()
    new_qty = data.get('quantity')
    if new_qty is None or new_qty < 0:
        return jsonify({'success': False, 'message': 'Quantité invalide'}), 400
    
    stock.quantity = int(new_qty)
    db.session.commit()
    return jsonify({'success': True, 'message': 'Quantité mise à jour'})


@main_bp.route("/api/medicines/list", methods=["GET"])
def api_medicines_list():
    """Liste de tous les médicaments (pour le select)."""
    medicines = Medicine.query.order_by(Medicine.name).all()
    result = [{
        'id': m.id,
        'name': m.name,
        'generic_name': m.generic_name,
        'manufacturer': m.manufacturer
    } for m in medicines]
    return jsonify({'success': True, 'medicines': result})


@main_bp.route("/stocks")
def stocks():
    if 'user_id' not in session:
        flash("Veuillez vous connecter.", "warning")
        return redirect(url_for("main.login"))
    user = User.query.get(session['user_id'])
    if user.role != 'pharmacien':
        flash("Accès réservé aux pharmaciens.", "danger")
        return redirect(url_for("main.dashboard"))
    return render_template("admin/stocks.html")


    # ------------------------------------------------------------------
# API Gestion des médicaments (admin & pharmacien)
# ------------------------------------------------------------------
@main_bp.route("/api/medicines/<int:medicine_id>", methods=["GET"])
def api_get_medicine(medicine_id):
    """Récupère un médicament par son ID."""
    if 'user_id' not in session:
        return jsonify({'success': False, 'message': 'Non authentifié'}), 401
    
    user = User.query.get(session['user_id'])
    if user.role not in ['admin', 'pharmacien']:
        return jsonify({'success': False, 'message': 'Permission refusée'}), 403
    
    medicine = Medicine.query.get(medicine_id)
    if not medicine:
        return jsonify({'success': False, 'message': 'Médicament introuvable'}), 404
    
    return jsonify({
        'success': True,
        'medicine': {
            'id': medicine.id,
            'name': medicine.name,
            'generic_name': medicine.generic_name,
            'manufacturer': medicine.manufacturer,
            'category': getattr(medicine, 'category', ''),
            'prescription_required': medicine.prescription_required,
            'image_url': medicine.image_url or '',
            'description': getattr(medicine, 'description', ''),
            'reorder_level': getattr(medicine, 'reorder_level', 10),
            'unit': getattr(medicine, 'unit', 'boîte'),
            'dosage': medicine.dosage or '',
            'form': medicine.form or ''
        }
    })


@main_bp.route("/api/medicines/<int:medicine_id>", methods=["PUT"])
def api_update_medicine(medicine_id):
    """Met à jour les informations d'un médicament."""
    if 'user_id' not in session:
        return jsonify({'success': False, 'message': 'Non authentifié'}), 401
    
    user = User.query.get(session['user_id'])
    if user.role not in ['admin', 'pharmacien']:
        return jsonify({'success': False, 'message': 'Permission refusée'}), 403
    
    medicine = Medicine.query.get(medicine_id)
    if not medicine:
        return jsonify({'success': False, 'message': 'Médicament introuvable'}), 404
    
    data = request.get_json()
    if not data:
        return jsonify({'success': False, 'message': 'Données JSON invalides'}), 400
    
    # Champs autorisés (ceux du formulaire)
    allowed_fields = ['name', 'generic_name', 'manufacturer', 'category',
                      'prescription_required', 'image_url', 'description',
                      'reorder_level', 'unit', 'dosage', 'form']
    for field in allowed_fields:
        if field in data:
            if field == 'prescription_required':
                setattr(medicine, field, bool(data[field]))
            elif field in ['reorder_level']:
                setattr(medicine, field, int(data[field]) if data[field] else None)
            else:
                setattr(medicine, field, data[field] if data[field] else '')
    
    # Validation minimale
    if not medicine.name:
        return jsonify({'success': False, 'message': 'Le nom du médicament est obligatoire'}), 400
    
    try:
        db.session.commit()
        return jsonify({'success': True, 'message': 'Médicament mis à jour avec succès'})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': f'Erreur lors de la mise à jour : {str(e)}'}), 500


@main_bp.route("/api/medicines/<int:medicine_id>", methods=["DELETE"])
def api_delete_medicine(medicine_id):
    """
    Supprime un médicament et toutes ses lignes de stock associées.
    (Cascade: les QR codes liés sont également supprimés via relationship)
    """
    if 'user_id' not in session:
        return jsonify({'success': False, 'message': 'Non authentifié'}), 401
    
    user = User.query.get(session['user_id'])
    if user.role not in ['admin', 'pharmacien']:
        return jsonify({'success': False, 'message': 'Permission refusée'}), 403
    
    medicine = Medicine.query.get(medicine_id)
    if not medicine:
        return jsonify({'success': False, 'message': 'Médicament introuvable'}), 404
    
    try:
        # Supprimer les stocks (nécessaire si cascade non configurée)
        Stock.query.filter_by(medicine_id=medicine_id).delete()
        # Supprimer les QR codes liés
        QRCode.query.filter_by(medicine_id=medicine_id).delete()
        # Supprimer le médicament
        db.session.delete(medicine)
        db.session.commit()
        return jsonify({'success': True, 'message': 'Médicament et ses stocks supprimés'})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': f'Erreur lors de la suppression : {str(e)}'}), 500


@main_bp.route("/api/medicines/<int:medicine_id>/stocks", methods=["GET"])
def api_get_medicine_stocks(medicine_id):
    """Liste toutes les lignes de stock (batchs) pour un médicament donné."""
    if 'user_id' not in session:
        return jsonify({'success': False, 'message': 'Non authentifié'}), 401
    
    user = User.query.get(session['user_id'])
    if user.role not in ['admin', 'pharmacien']:
        return jsonify({'success': False, 'message': 'Permission refusée'}), 403
    
    medicine = Medicine.query.get(medicine_id)
    if not medicine:
        return jsonify({'success': False, 'message': 'Médicament introuvable'}), 404
    
    stocks = Stock.query.filter_by(medicine_id=medicine_id).all()
    stocks_data = []
    for s in stocks:
        stocks_data.append({
            'id': s.id,
            'batch_number': s.batch_number or '',
            'quantity': s.quantity,
            'price': float(s.price) if s.price else 0,
            'expiry_date': s.expiry_date.isoformat() if s.expiry_date else None,
            'pharmacy_id': s.pharmacy_id,
            'pharmacy_name': s.pharmacy.name if s.pharmacy else ''
        })
    return jsonify({'success': True, 'stocks': stocks_data})

@main_bp.route("/medicines/edit")
def edit_medicine_page():
    """Affiche le formulaire de modification d'un médicament."""
    if 'user_id' not in session:
        flash("Veuillez vous connecter.", "warning")
        return redirect(url_for("main.login"))
    
    user = User.query.get(session['user_id'])
    if user.role not in ['admin', 'pharmacien']:
        flash("Accès réservé aux pharmaciens et administrateurs.", "danger")
        return redirect(url_for("main.dashboard"))
    
    medicine_id = request.args.get('id')
    if not medicine_id:
        flash("Aucun médicament spécifié.", "danger")
        return redirect(url_for("main.stocks"))
    
    medicine = Medicine.query.get(medicine_id)
    if not medicine:
        flash("Médicament introuvable.", "danger")
        return redirect(url_for("main.stocks"))
    
    return render_template("admin/medicine_edit.html", medicine=medicine)

# ------------------------------------------------------------------
# Scan patient (vérification authentification sans insertion)
# ------------------------------------------------------------------
@main_bp.route("/patient/scan")
def patient_scan():
    """Page de vérification anti-contrefaçon pour les patients."""
    if 'user_id' not in session:
        flash("Veuillez vous connecter en tant que patient.", "warning")
        return redirect(url_for("main.login"))
    user = User.query.get(session['user_id'])
    if user.role != 'patient':
        flash("Cette page est réservée aux patients.", "danger")
        return redirect(url_for("main.dashboard"))
    return render_template("admin/patient_scan.html")