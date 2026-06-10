import secrets
import random
import os
import cv2
import numpy as np
from flask import Blueprint, render_template, request, redirect, url_for, flash, session, jsonify
from werkzeug.utils import secure_filename
from db import db
from models import User, Pharmacy, Medicine, Order, Stock, QRCode
from email_utils import send_email
from datetime import datetime
from pyzbar.pyzbar import decode

main_bp = Blueprint('main', __name__)

UPLOAD_FOLDER = 'uploads'
ALLOWED_EXTENSIONS = {'pdf', 'png', 'jpg', 'jpeg'}
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

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
# API Scan et upload QR code
# ------------------------------------------------------------------
@main_bp.route("/scan")
def scan_page():
    if 'user_id' not in session:
        flash("Veuillez vous connecter.", "warning")
        return redirect(url_for("main.login"))
    return render_template("admin/scan.html")

@main_bp.route("/api/scan", methods=["POST"])
def api_scan():
    if 'user_id' not in session:
        return jsonify({'success': False, 'message': 'Non authentifié'}), 401
    
    data = request.get_json()
    scanned_code = data.get('code', '').strip()
    if not scanned_code:
        return jsonify({'success': False, 'message': 'Code vide'}), 400
    
    user = User.query.get(session['user_id'])
    role = user.role
    
    qr = QRCode.query.filter_by(code=scanned_code).first()
    if qr:
        medicine = qr.medicine
        if qr.status == 'used' and role != 'pharmacien':
            return jsonify({
                'success': False,
                'message': '⚠️ Ce médicament a déjà été scanné auparavant ! Possible contrefaçon.'
            })
        if role == 'patient' and qr.status == 'active':
            qr.status = 'used'
            qr.verified_at = datetime.utcnow()
            qr.verified_by = 'patient'
            db.session.commit()
        return jsonify({
            'success': True,
            'medicine': {
                'name': medicine.name,
                'generic_name': medicine.generic_name,
                'manufacturer': medicine.manufacturer,
                'dosage': medicine.dosage,
                'form': medicine.form,
                'prescription_required': medicine.prescription_required,
                'authentic': qr.status == 'used' if role == 'patient' else True
            }
        })
    else:
        return jsonify({
            'success': False,
            'not_found': True,
            'message': 'Médicament non trouvé dans la base.'
        }), 404

@main_bp.route("/api/upload-qrcode", methods=["POST"])
def api_upload_qrcode():
    """Reçoit une image, utilise pyzbar pour extraire le QR code"""
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
        
        decoded_objects = decode(img)
        
        if not decoded_objects:
            return jsonify({'success': False, 'message': 'Aucun QR code trouvé dans l\'image'}), 404
        
        qr_data = decoded_objects[0].data.decode('utf-8')
        return jsonify({'success': True, 'code': qr_data})
    
    except Exception as e:
        print(f"Erreur décodage: {e}")
        return jsonify({'success': False, 'message': 'Erreur lors du décodage'}), 500

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