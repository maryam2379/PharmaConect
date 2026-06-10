# models.py
# Modèles Flask-SQLAlchemy pour MediTrack Cameroun

from flask_sqlalchemy import SQLAlchemy
from flask_bcrypt import Bcrypt
from datetime import datetime

db = SQLAlchemy()
bcrypt = Bcrypt()


class User(db.Model):
    __tablename__ = 'users'

    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(120), unique=True, nullable=False)
    phone = db.Column(db.String(20), unique=True, nullable=False)
    password_hash = db.Column(db.String(128), nullable=False)
    role = db.Column(db.String(20), nullable=False)  # patient, pharmacien, admin, grossiste
    full_name = db.Column(db.String(100))
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # Relations
    pharmacy = db.relationship('Pharmacy', back_populates='manager', uselist=False)
    orders = db.relationship('Order', back_populates='user')
    searches = db.relationship('PatientSearchHistory', back_populates='patient')

    def set_password(self, password):
        self.password_hash = bcrypt.generate_password_hash(password).decode('utf-8')

    def check_password(self, password):
        return bcrypt.check_password_hash(self.password_hash, password)


class Pharmacy(db.Model):
    __tablename__ = 'pharmacies'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(150), nullable=False)
    license_number = db.Column(db.String(50), unique=True, nullable=False)
    address = db.Column(db.String(200))
    city = db.Column(db.String(50))
    latitude = db.Column(db.Float)
    longitude = db.Column(db.Float)
    phone = db.Column(db.String(20))
    email = db.Column(db.String(120))
    subscription_plan = db.Column(db.String(20), default='basic')  # basic, standard, premium
    subscription_end = db.Column(db.DateTime)
    is_verified = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    manager_id = db.Column(db.Integer, db.ForeignKey('users.id'))

    # Relations
    manager = db.relationship('User', back_populates='pharmacy')
    stocks = db.relationship('Stock', back_populates='pharmacy', cascade='all, delete-orphan')
    orders = db.relationship('Order', back_populates='pharmacy')
    qrcodes = db.relationship('QRCode', back_populates='pharmacy')
    offline_syncs = db.relationship('OfflineSync', back_populates='pharmacy')


class Medicine(db.Model):
    __tablename__ = 'medicines'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(150), nullable=False)
    generic_name = db.Column(db.String(150))
    manufacturer = db.Column(db.String(100))
    dosage = db.Column(db.String(50))      # ex: 500mg
    form = db.Column(db.String(50))        # comprimé, sirop, injectable
    prescription_required = db.Column(db.Boolean, default=False)
    image_url = db.Column(db.String(300))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # Relations
    stocks = db.relationship('Stock', back_populates='medicine')
    qr_codes = db.relationship('QRCode', back_populates='medicine')
    order_items = db.relationship('OrderItem', back_populates='medicine')


class Stock(db.Model):
    __tablename__ = 'stocks'

    id = db.Column(db.Integer, primary_key=True)
    quantity = db.Column(db.Integer, nullable=False, default=0)
    batch_number = db.Column(db.String(50))
    expiry_date = db.Column(db.Date, nullable=False)
    price = db.Column(db.Numeric(10, 2))   # prix unitaire en FCFA
    last_updated = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    pharmacy_id = db.Column(db.Integer, db.ForeignKey('pharmacies.id'), nullable=False)
    medicine_id = db.Column(db.Integer, db.ForeignKey('medicines.id'), nullable=False)

    pharmacy = db.relationship('Pharmacy', back_populates='stocks')
    medicine = db.relationship('Medicine', back_populates='stocks')


class QRCode(db.Model):
    __tablename__ = 'qrcodes'

    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(200), unique=True, nullable=False)
    serial_number = db.Column(db.String(100))
    status = db.Column(db.String(20), default='active')  # active, used, expired, fake
    verified_at = db.Column(db.DateTime)
    verified_by = db.Column(db.String(20))   # patient_id ou anonyme

    medicine_id = db.Column(db.Integer, db.ForeignKey('medicines.id'), nullable=False)
    pharmacy_id = db.Column(db.Integer, db.ForeignKey('pharmacies.id'))

    medicine = db.relationship('Medicine', back_populates='qr_codes')
    pharmacy = db.relationship('Pharmacy', back_populates='qrcodes')


class Supplier(db.Model):
    __tablename__ = 'suppliers'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(150), nullable=False)
    contact = db.Column(db.String(20))
    email = db.Column(db.String(120))
    address = db.Column(db.String(200))

    orders = db.relationship('Order', back_populates='supplier')


class Order(db.Model):
    __tablename__ = 'orders'

    id = db.Column(db.Integer, primary_key=True)
    reference = db.Column(db.String(50), unique=True, nullable=False)
    status = db.Column(db.String(20), default='pending')  # pending, confirmed, shipped, delivered
    total_amount = db.Column(db.Numeric(12, 2))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    delivered_at = db.Column(db.DateTime)

    pharmacy_id = db.Column(db.Integer, db.ForeignKey('pharmacies.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    supplier_id = db.Column(db.Integer, db.ForeignKey('suppliers.id'))

    pharmacy = db.relationship('Pharmacy', back_populates='orders')
    user = db.relationship('User', back_populates='orders')
    supplier = db.relationship('Supplier', back_populates='orders')
    items = db.relationship('OrderItem', back_populates='order', cascade='all, delete-orphan')


class OrderItem(db.Model):
    __tablename__ = 'order_items'

    id = db.Column(db.Integer, primary_key=True)
    quantity = db.Column(db.Integer, nullable=False)
    unit_price = db.Column(db.Numeric(10, 2))

    order_id = db.Column(db.Integer, db.ForeignKey('orders.id'), nullable=False)
    medicine_id = db.Column(db.Integer, db.ForeignKey('medicines.id'), nullable=False)

    order = db.relationship('Order', back_populates='items')
    medicine = db.relationship('Medicine', back_populates='order_items')


class PatientSearchHistory(db.Model):
    __tablename__ = 'patient_search_history'

    id = db.Column(db.Integer, primary_key=True)
    medicine_name = db.Column(db.String(150))
    searched_at = db.Column(db.DateTime, default=datetime.utcnow)

    patient_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    found_pharmacy_id = db.Column(db.Integer, db.ForeignKey('pharmacies.id'))

    patient = db.relationship('User', back_populates='searches')
    pharmacy = db.relationship('Pharmacy')


class OfflineSync(db.Model):
    __tablename__ = 'offline_sync'

    id = db.Column(db.Integer, primary_key=True)
    pending_updates = db.Column(db.JSON)   # ex: {"stock_id": 5, "new_quantity": 100}
    synced_at = db.Column(db.DateTime)

    pharmacy_id = db.Column(db.Integer, db.ForeignKey('pharmacies.id'), nullable=False)

    pharmacy = db.relationship('Pharmacy', back_populates='offline_syncs')