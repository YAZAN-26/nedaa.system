from fastapi import FastAPI, Depends, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sqlalchemy import create_engine, Column, Integer, String, Boolean, DateTime
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session
import enum
from datetime import datetime, timedelta

# إعداد قاعدة البيانات المحلية
SQLALCHEMY_DATABASE_URL = "sqlite:///./nedaa_system.db"
engine = create_engine(SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

app = FastAPI(title="Nedaa System API", version="2.0")

# إعدادات البريد الإلكتروني والدعم الفني
SYSTEM_EMAIL = "Nedaa.System@hotmail.com"
SUPPORT_EMAIL = "Nedaa.Help@hotmail.com"

# السماح بالاتصال من كافة الواجهات
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# حالات الطلب المعتمدة
class OrderStatus(str, enum.Enum):
    preparing = "يتم التحضير"
    ready = "جاهز للاستلام"
    completed = "تم الاستلام"

# --- 1. نماذج قاعدة البيانات (Database Models) ---

class BranchModel(Base):
    """جدول الفروع والمقاهي المشتركة"""
    __tablename__ = "branches"
    
    id = Column(Integer, primary_key=True, index=True)
    cafe_name = Column(String, index=True)           # اسم المقهى / المطعم
    branch_name = Column(String)                     # اسم الفرع (مثلاً: فرع مسرة)
    logo_url = Column(String, nullable=True)         # رابط الهوية البصرية / اللوجو
    primary_color = Column(String, default="#4F46E5") # لون الثيم الرئيسي
    
    city = Column(String)                            # المدينة
    district = Column(String)                        # الحي
    location_url = Column(String, nullable=True)     # رابط Google Maps
    
    username = Column(String, unique=True, index=True)
    password = Column(String)
    
    # الاشتراكات والتجربة
    subscription_plan = Column(String, default="Free Trial") 
    is_active = Column(Boolean, default=True)
    free_orders_left = Column(Integer, default=10)   # عرض أول 10 طلبات مجانية
    expires_at = Column(DateTime)
    terms_accepted = Column(Boolean, default=True)   # الموافقة على الشروط والأحكام
    created_at = Column(DateTime, default=datetime.utcnow)

class OrderModel(Base):
    """جدول الطلبات"""
    __tablename__ = "orders"
    
    id = Column(Integer, primary_key=True, index=True)
    branch_id = Column(Integer, index=True)
    order_number = Column(String)
    customer_phone = Column(String, nullable=True)
    status = Column(String, default=OrderStatus.preparing)
    created_at = Column(DateTime, default=datetime.utcnow)

class SupportTicketModel(Base):
    """جدول تذاكر الدعم الفني الموجهة إلى Nedaa.Help@hotmail.com"""
    __tablename__ = "support_tickets"
    
    id = Column(Integer, primary_key=True, index=True)
    branch_id = Column(Integer, index=True)
    cafe_name = Column(String)
    subject = Column(String)
    message = Column(String)
    status = Column(String, default="مفتوحة") # مفتوحة, قيد المعالجة, مغلقة
    created_at = Column(DateTime, default=datetime.utcnow)

Base.metadata.create_all(bind=engine)

# --- 2. نماذج التحقق (Pydantic Schemas) ---

class BranchRegister(BaseModel):
    cafe_name: str
    branch_name: str
    logo_url: str = None
    primary_color: str = "#4F46E5"
    city: str
    district: str
    location_url: str = None
    username: str
    password: str
    terms_accepted: bool

class BranchLogin(BaseModel):
    username: str
    password: str

class OrderCreate(BaseModel):
    branch_id: int
    order_number: str
    customer_phone: str = None

class StatusUpdate(BaseModel):
    status: OrderStatus

class TicketCreate(BaseModel):
    branch_id: int
    subject: str
    message: str

class AdminLogin(BaseModel):
    password: str

class SubscriptionExtend(BaseModel):
    branch_id: int
    days: int

# --- 3. الدوال المساعدة ---

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def clean_old_orders(db: Session):
    """حذف الطلبات القديمة التي مضى عليها أكثر من 7 أيام أسبوعياً"""
    week_ago = datetime.utcnow() - timedelta(days=7)
    db.query(OrderModel).filter(OrderModel.created_at < week_ago).delete()
    db.commit()

# --- 4. مسارات النظام (API Endpoints) ---

@app.post("/branches/register")
def register_branch(branch: BranchRegister, db: Session = Depends(get_db)):
    """تسجيل فرع جديد مع تفعيل فترة التجربة (أول 10 طلبات مجاناً)"""
    if not branch.terms_accepted:
        raise HTTPException(status_code=400, detail="يجب الموافقة على الشروط والأحكام لإكمال التسجيل.")
    
    existing_user = db.query(BranchModel).filter(BranchModel.username == branch.username).first()
    if existing_user:
        raise HTTPException(status_code=400, detail="اسم المستخدم مستخدم بالفعل لفرع آخر.")
    
    # تحديد تاريخ انتهاء مبدئي (30 يوم تجريبية كحد أقصى للـ 10 طلبات)
    expiry = datetime.utcnow() + timedelta(days=30)
    
    new_branch = BranchModel(
        cafe_name=branch.cafe_name,
        branch_name=branch.branch_name,
        logo_url=branch.logo_url,
        primary_color=branch.primary_color,
        city=branch.city,
        district=branch.district,
        location_url=branch.location_url,
        username=branch.username,
        password=branch.password,
        expires_at=expiry,
        terms_accepted=branch.terms_accepted
    )
    db.add(new_branch)
    db.commit()
    db.refresh(new_branch)
    return {
        "message": "تم تسجيل الفرع بنجاح! تم منحك أول 10 طلبات مجاناً.",
        "branch_id": new_branch.id,
        "free_orders_left": new_branch.free_orders_left
    }

@app.post("/branches/login")
def login_branch(creds: BranchLogin, db: Session = Depends(get_db)):
    """تسجيل دخول الكاشير/الفرع"""
    branch = db.query(BranchModel).filter(
        BranchModel.username == creds.username, 
        BranchModel.password == creds.password
    ).first()
    
    if not branch:
        raise HTTPException(status_code=401, detail="اسم المستخدم أو كلمة المرور غير صحيحة.")
    
    if not branch.is_active or datetime.utcnow() > branch.expires_at:
        raise HTTPException(status_code=403, detail="عذراً، انقضت فترة الاشتراك الخاصة بهذا الفرع. يرجى التواصل مع الدعم التجديد.")
        
    return {
        "message": "تم تسجيل الدخول بنجاح",
        "branch_id": branch.id,
        "cafe_name": branch.cafe_name,
        "branch_name": branch.branch_name,
        "logo_url": branch.logo_url,
        "primary_color": branch.primary_color,
        "free_orders_left": branch.free_orders_left,
        "expires_at": branch.expires_at.strftime("%Y-%m-%d")
    }

@app.post("/orders/")
def create_order(order: OrderCreate, db: Session = Depends(get_db)):
    """إنشاء طلب جديد مع التحقق من الرصيد والاشتراك"""
    clean_old_orders(db)
    
    branch = db.query(BranchModel).filter(BranchModel.id == order.branch_id).first()
    if not branch or not branch.is_active:
        raise HTTPException(status_code=403, detail="حساب الفرع غير نشط.")
    
    # التحقق من الرصيد المجاني والاشتراك
    if branch.free_orders_left <= 0 and datetime.utcnow() > branch.expires_at:
        raise HTTPException(status_code=402, detail="انتهى رصيد الطلبات المجانية والاشتراك. يرجى التجديد للاستمرار.")
    
    # خصم من الطلبات المجانية إن وجدت
    if branch.free_orders_left > 0:
        branch.free_orders_left -= 1
        
    db_order = OrderModel(
        branch_id=order.branch_id,
        order_number=order.order_number,
        customer_phone=order.customer_phone,
        status=OrderStatus.preparing,
        created_at=datetime.utcnow()
    )
    db.add(db_order)
    db.commit()
    db.refresh(db_order)
    return {
        "message": "تم إنشاء الطلب بنجاح", 
        "order_id": db_order.id, 
        "order_number": db_order.order_number,
        "free_orders_left": branch.free_orders_left
    }

@app.get("/orders/{branch_id}")
def get_branch_orders(branch_id: int, db: Session = Depends(get_db)):
    """عرض طلبات الفرع"""
    clean_old_orders(db)
    orders = db.query(OrderModel).filter(OrderModel.branch_id == branch_id).all()
    branch = db.query(BranchModel).filter(BranchModel.id == branch_id).first()
    return {
        "orders": orders,
        "cafe_name": branch.cafe_name if branch else "",
        "branch_name": branch.branch_name if branch else "",
        "logo_url": branch.logo_url if branch else "",
        "primary_color": branch.primary_color if branch else "#4F46E5",
        "free_orders_left": branch.free_orders_left if branch else 0,
        "support_email": SUPPORT_EMAIL
    }

@app.put("/orders/{order_id}/status")
def update_order_status(order_id: int, status_update: StatusUpdate, db: Session = Depends(get_db)):
    """تحديث حالة الطلب"""
    order = db.query(OrderModel).filter(OrderModel.id == order_id).first()
    if not order:
        raise HTTPException(status_code=404, detail="الطلب غير موجود")
    order.status = status_update.status
    db.commit()
    return {"message": "تم تحديث حالة الطلب بنجاح", "new_status": order.status}

# --- 5. مسارات الدعم الفني وتذاكر الصيانة ---

@app.post("/support/tickets")
def create_support_ticket(ticket: TicketCreate, db: Session = Depends(get_db)):
    """إنشاء تذكرة دعم فني من الفرع وتوجيهها للدعم الفني"""
    branch = db.query(BranchModel).filter(BranchModel.id == ticket.branch_id).first()
    if not branch:
        raise HTTPException(status_code=404, detail="الفرع غير موجود")
        
    new_ticket = SupportTicketModel(
        branch_id=ticket.branch_id,
        cafe_name=f"{branch.cafe_name} - {branch.branch_name}",
        subject=ticket.subject,
        message=ticket.message
    )
    db.add(new_ticket)
    db.commit()
    return {
        "message": f"تم إرسال تذكرة الدعم بنجاح إلى فريق الدعم الفني ({SUPPORT_EMAIL}). سنرد عليك في أقرب وقت.",
        "ticket_id": new_ticket.id
    }

# --- 6. لوحة الأدمن العليا (Super Admin Dashboard) ---

@app.post("/admin/login")
def admin_login(creds: AdminLogin):
    """تسجيل دخول الأدمن الرئيسي (كلمة السر السرية)"""
    if creds.password == "Nedaa2026AdminSecret": # كلمة السر الخاصة بك
        return {"message": "مرحباً بك في لوحة الإدارة العليا لنظام نِداء"}
    raise HTTPException(status_code=401, detail="كلمة السر غير صحيحة.")

@app.get("/admin/branches")
def admin_get_branches(db: Session = Depends(get_db)):
    """عرض جميع الفروع والمقاهي المشتركة"""
    return db.query(BranchModel).all()

@app.get("/admin/tickets")
def admin_get_tickets(db: Session = Depends(get_db)):
    """عرض جميع تذاكر الدعم الفني الواردة"""
    return db.query(SupportTicketModel).all()

@app.post("/admin/extend-subscription")
def admin_extend_subscription(ext: SubscriptionExtend, db: Session = Depends(get_db)):
    """تمديد اشتراك فرع بعد سداد الرسوم"""
    branch = db.query(BranchModel).filter(BranchModel.id == ext.branch_id).first()
    if not branch:
        raise HTTPException(status_code=404, detail="الفرع غير موجود")
    
    branch.expires_at = datetime.utcnow() + timedelta(days=ext.days)
    branch.is_active = True
    db.commit()
    return {"message": f"تم تمديد اشتراك فرع {branch.cafe_name} بنجاح لمدة {ext.days} يوم."}