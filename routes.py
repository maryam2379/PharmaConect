import secrets
import random
import os
from flask import Blueprint, render_template, request, redirect, url_for, flash, session, jsonify
from werkzeug.utils import secure_filename
from db import db                     # instance unique
from models import User, Pharmacy, Medicine, Order   # ajout des modèles manquants
from email_utils import send_email

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
    
    role_dashboards = {
        'patient': 'main.dashboard_patient',
        'pharmacien': 'main.dashboard_pharmacien',
        'admin': 'main.dashboard_admin',
        'grossiste': 'main.dashboard_grossiste'
    }
    dashboard = role_dashboards.get(user.role, 'main.home')
    flash(f"Bienvenue {user.full_name} !", "success")
    return redirect(url_for(dashboard))

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

    # Initialisation de toutes les variables attendues par le template
    stats = {}
    recent_searches = []
    critical_stock = []
    recent_users = []
    pending_pharmacies = []
    recent_orders = []

    if role == 'patient':
        # Remplacez ces valeurs par de vraies requêtes SQLAlchemy
        stats['recent_searches'] = 0
        stats['scans'] = 0
        stats['nearby_pharmacies'] = 0
        # recent_searches = ... (ex: user.searches.all())

    elif role == 'pharmacien':
        stats['total_stock'] = 0
        stats['low_stock'] = 0
        stats['pending_orders'] = 0
        # critical_stock = ...

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
        # recent_orders = ...

    return render_template("admin/dashboard.html",
                           user=user,
                           stats=stats,
                           recent_searches=recent_searches,
                           critical_stock=critical_stock,
                           recent_users=recent_users,
                           pending_pharmacies=pending_pharmacies,
                           recent_orders=recent_orders)

# Assurez-vous que cette route est présente dans routes.py
@main_bp.route("/anti-counterfeit")
def anti_counterfeit():
    """Page de vérification anti-contrefaçon avec caméra"""
    return render_template("anti_counterfeit.html")

@main_bp.route("/pharmacies")
def pharmacies():
    """Page affichant toutes les pharmacies avec carte interactive"""
    return render_template("pharmacies.html")

@main_bp.route("/faq")
def faq():
    """Page Foire Aux Questions"""
    return render_template("layout/faq.html")