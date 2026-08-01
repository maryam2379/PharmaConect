import secrets
import random
import json

from django.shortcuts import render, redirect
from django.contrib.auth import authenticate, login as auth_login, logout as auth_logout
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from .models import User
from .services import send_otp_email, send_verification_email
from pharmacies.models import Pharmacy


def home(request):
    return render(request, "index.html")


def faq(request):
    return render(request, 'layout/faq.html')


def newsletter_subscribe(request):
    if request.method == 'POST':
        email = request.POST.get('email')
        # Traitement de l'inscription à la newsletter
        messages.success(request, "Inscription à la newsletter réussie !")
        return redirect('auth:home')
    return redirect('auth:home')


# ------------------------------------------------------------------
# Inscription
# ------------------------------------------------------------------
def register(request):
    if request.method == "GET":
        return render(request, "auth/register.html")

    # Cas API (JSON)
    if request.content_type == "application/json":
        data = json.loads(request.body)
        role = data.get('role')
        email = data.get('email')
        password = data.get('password')
        profile_data = data.get('profile_data', {})
        uploaded_docs = data.get('documents', {})

        if not email or not password or not role:
            return JsonResponse({'success': False, 'message': 'Champs obligatoires manquants'}, status=400)

        if User.objects.filter(email=email).exists():
            return JsonResponse({'success': False, 'message': 'Email déjà utilisé'}, status=400)

        prenom = profile_data.get('prenom', '')
        nom = profile_data.get('nom', '')
        full_name = f"{prenom} {nom}".strip() or email.split('@')[0]
        phone = profile_data.get('telephone', '')

        new_user = User(
            username=email,
            email=email,
            phone=phone,
            first_name=prenom,
            last_name=nom,
            role=role,
            is_active=False,
            is_verified=False,
            verification_token=secrets.token_urlsafe(32),
            otp_code=f"{random.randint(100000, 999999)}",
            documents=uploaded_docs,
        )
        new_user.set_password(password)
        new_user.save()

        if role == 'pharmacien':
            Pharmacy.objects.create(
                name=profile_data.get('nomPharmacie', ''),
                license_number=profile_data.get('ordreOnpc', ''),
                address=profile_data.get('geoInput', ''),
                city=profile_data.get('region', ''),
                phone=phone,
                email=email,
                manager=new_user,
                is_verified=False,
            )

        # Envoyer l'email de vérification avec gestion d'erreur
        email_sent = send_verification_email(new_user, _build_verification_url(request, new_user.verification_token))
        
        if email_sent:
            print(f"✅ Email de vérification envoyé à {new_user.email}")
        else:
            print(f"❌ Échec d'envoi de l'email à {new_user.email}")

        upgrade_id = f"pharmaconnect-CM-{new_user.id:05d}"
        return JsonResponse({
            'success': True,
            'upgrade_id': upgrade_id,
            'email': new_user.email,
            'message': 'Inscription réussie. Vérifiez votre boîte email.' if email_sent else 'Inscription réussie mais l\'email de vérification n\'a pas pu être envoyé. Veuillez contacter le support.',
        })

    # Cas formulaire classique
    email = request.POST.get("email")
    phone = request.POST.get("phone")
    full_name = request.POST.get("full_name", "")
    password = request.POST.get("password")
    role = request.POST.get("role")

    # Vérification des champs obligatoires
    if not email or not phone or not password or not role:
        messages.error(request, "Tous les champs sont obligatoires.")
        return redirect("auth:register")

    if User.objects.filter(email=email).exists() or User.objects.filter(phone=phone).exists():
        messages.error(request, "Un compte avec cet email ou téléphone existe déjà.")
        return redirect("auth:register")

    new_user = User(
        username=email,
        email=email,
        phone=phone,
        first_name=full_name.split(" ")[0] if full_name else "",
        last_name=" ".join(full_name.split(" ")[1:]) if full_name else "",
        role=role,
        is_active=False,
        is_verified=False,
        verification_token=secrets.token_urlsafe(32),
        otp_code=f"{random.randint(100000, 999999)}",
    )
    new_user.set_password(password)
    new_user.save()

    if role == "pharmacien":
        Pharmacy.objects.create(
            name=request.POST.get("pharmacy_name", ""),
            license_number=request.POST.get("license_number", ""),
            address=request.POST.get("pharmacy_address", ""),
            city=request.POST.get("pharmacy_city", ""),
            phone=request.POST.get("pharmacy_phone", phone),
            email=request.POST.get("pharmacy_email", email),
            manager=new_user,
            is_verified=False,
        )

    # Stocker l'ID de l'utilisateur en session pour la vérification
    request.session['pending_user_id'] = new_user.id
    
    # Envoyer l'email de vérification avec gestion d'erreur
    email_sent = send_verification_email(new_user, _build_verification_url(request, new_user.verification_token))
    
    if email_sent:
        print(f"✅ Email de vérification envoyé à {new_user.email}")
        messages.success(request, "Compte créé avec succès ! Un email de vérification vous a été envoyé.")
    else:
        print(f"❌ Échec d'envoi de l'email à {new_user.email}")
        messages.warning(request, "Compte créé avec succès ! Cependant, l'email de vérification n'a pas pu être envoyé. Veuillez contacter le support ou réessayer plus tard.")
    
    return redirect("auth:verification_choice")


def _build_verification_url(request, token):
    return request.build_absolute_uri(f"/verify-email/{token}/")


# ------------------------------------------------------------------
# Upload de documents
# ------------------------------------------------------------------
ALLOWED_EXTENSIONS = {'pdf', 'jpg', 'jpeg', 'png'}


def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


@require_http_methods(["POST"])
def upload_document(request):
    file = request.FILES.get('document')
    doc_type = request.POST.get('type', 'unknown')

    if not file:
        return JsonResponse({'success': False, 'message': 'Aucun fichier'}, status=400)
    if not allowed_file(file.name):
        return JsonResponse({'success': False, 'message': 'Type non autorisé (PDF, JPG, PNG)'}, status=400)

    from django.core.files.storage import default_storage
    filename = f"{doc_type}_{file.name}"
    path = default_storage.save(filename, file)

    return JsonResponse({
        'success': True,
        'path': path,
        'name': filename,
        'size': file.size,
    })


# ------------------------------------------------------------------
# Vérification (choix OTP ou lien email)
# ------------------------------------------------------------------
def verification_choice(request):
    if 'pending_user_id' not in request.session:
        messages.warning(request, "Aucune inscription en cours. Veuillez vous inscrire d'abord.")
        return redirect("auth:register")
    return render(request, "auth/verification_choice.html")


def send_otp_route(request):
    user_id = request.session.get('pending_user_id')
    if not user_id:
        messages.warning(request, "Aucune inscription en cours.")
        return redirect("auth:register")

    user = User.objects.filter(id=user_id).first()
    if user:
        email_sent = send_otp_email(user)
        if email_sent:
            print(f"✅ Code OTP envoyé à {user.email}")
            messages.info(request, "Un code OTP a été envoyé à votre adresse email.")
        else:
            print(f"❌ Échec d'envoi du code OTP à {user.email}")
            messages.error(request, "Erreur lors de l'envoi du code. Réessayez plus tard.")
    return redirect("auth:verify_otp")


def verify_otp(request):
    user_id = request.session.get('pending_user_id')
    if not user_id:
        return redirect("auth:register")

    user = User.objects.filter(id=user_id).first()
    if not user:
        messages.error(request, "Utilisateur non trouvé.")
        return redirect("auth:register")

    if request.method == "POST":
        entered_otp = request.POST.get("otp")
        if entered_otp == user.otp_code:
            user.is_active = True
            user.is_verified = True
            user.verification_token = None
            user.otp_code = None
            user.save()
            request.session.pop('pending_user_id', None)
            messages.success(request, "Votre compte a été vérifié avec succès ! Vous pouvez vous connecter.")
            return redirect("auth:login")
        else:
            messages.error(request, "Code OTP invalide.")

    return render(request, "auth/verify_otp.html", {"email": user.email if user else ""})


def send_verification_link(request):
    user_id = request.session.get('pending_user_id')
    if not user_id:
        return redirect("auth:register")

    user = User.objects.filter(id=user_id).first()
    if user:
        url = _build_verification_url(request, user.verification_token)
        email_sent = send_verification_email(user, url)
        
        if email_sent:
            print(f"✅ Lien de vérification envoyé à {user.email}")
            messages.info(request, "Un lien de vérification a été envoyé à votre adresse email.")
        else:
            print(f"❌ Échec d'envoi du lien de vérification à {user.email}")
            messages.error(request, "Erreur d'envoi. Réessayez plus tard.")
    return redirect("auth:verification_choice")


def verify_email(request, token):
    user = User.objects.filter(verification_token=token).first()
    if user:
        user.is_active = True
        user.is_verified = True
        user.verification_token = None
        user.otp_code = None
        user.save()
        request.session.pop('pending_user_id', None)
        messages.success(request, "Votre adresse email a été vérifiée. Vous pouvez maintenant vous connecter.")
        return redirect("auth:login")
    else:
        messages.error(request, "Lien de vérification invalide ou expiré.")
        return redirect("auth:register")


# ------------------------------------------------------------------
# Connexion / Déconnexion
# ------------------------------------------------------------------
def login_view(request):
    if request.method == "GET":
        return render(request, "auth/login.html")

    email = request.POST.get("email")
    password = request.POST.get("password")
    remember = request.POST.get("remember") == "on"

    if not email or not password:
        messages.error(request, "Veuillez remplir tous les champs.")
        return redirect("auth:login")

    # authenticate() utilise USERNAME_FIELD -> on cherche par email
    user_obj = User.objects.filter(email=email).first()
    if not user_obj or not user_obj.check_password(password):
        messages.error(request, "Email ou mot de passe incorrect.")
        return redirect("auth:login")

    if not user_obj.is_verified:
        messages.warning(request, "Votre compte n'est pas encore vérifié. Vérifiez votre boîte email.")
        return redirect("auth:login")

    if not user_obj.is_active:
        messages.error(request, "Votre compte est désactivé. Contactez l'administrateur.")
        return redirect("auth:login")

    user = authenticate(request, username=user_obj.username, password=password)
    if user is None:
        messages.error(request, "Erreur d'authentification.")
        return redirect("auth:login")

    auth_login(request, user)

    if not remember:
        request.session.set_expiry(0)  # expire à la fermeture du navigateur

    messages.success(request, f"Bienvenue {user.get_full_name() or user.email} !")
    
    # Redirection selon le rôle
    if user.role == "pharmacien":
        return redirect("pharmacies:dashboard")
    elif user.role == "grossiste":
        return redirect("wholesalers:dashboard")
    else:
        return redirect("patients:dashboard")


def logout_view(request):
    auth_logout(request)
    messages.info(request, "Vous avez été déconnecté avec succès.")
    return redirect("auth:login")


# ------------------------------------------------------------------
# Dashboard / Profil
# ------------------------------------------------------------------
@login_required
def dashboard(request):
    context = {"user": request.user}

    if request.user.role == "pharmacien":
        pharmacy = Pharmacy.objects.filter(manager=request.user).first()
        context["pharmacy"] = pharmacy

    return render(request, "admin/patients/dashboard.html", context)


@login_required
def profile(request):
    if request.method == "POST":
        request.user.first_name = request.POST.get("first_name", request.user.first_name)
        request.user.last_name = request.POST.get("last_name", request.user.last_name)
        request.user.phone = request.POST.get("phone", request.user.phone)
        request.user.save()
        messages.success(request, "Profil mis à jour.")
        return redirect("auth:profile")

    return render(request, "admin/profile.html", {"user": request.user})