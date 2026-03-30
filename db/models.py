from sqlalchemy import create_engine, Column, Integer, Float, Boolean, String, DateTime
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from datetime import datetime

# SQLite — Jetson'da da sorunsuz çalışır
engine = create_engine(
    "sqlite:///teknofest_iha.db",
    connect_args={"check_same_thread": False}
)

Base = declarative_base()
SessionLocal = sessionmaker(bind=engine)

# ─────────────────────────────────────────
# Telemetri kayıtları
# ─────────────────────────────────────────
class Telemetri(Base):
    __tablename__ = "telemetri"

    id        = Column(Integer, primary_key=True, autoincrement=True)
    zaman     = Column(DateTime, default=datetime.utcnow)
    enlem     = Column(Float)
    boylam    = Column(Float)
    irtifa    = Column(Float)
    dikilme   = Column(Float)
    yonelme   = Column(Float)
    yatis     = Column(Float)
    hiz       = Column(Float)
    batarya   = Column(Float)
    otonom    = Column(Boolean)
    kilitlenme = Column(Boolean, default=False)

# ─────────────────────────────────────────
# Kilitlenme kayıtları
# ─────────────────────────────────────────
class Kilitlenme(Base):
    __tablename__ = "kilitlenme"

    id             = Column(Integer, primary_key=True, autoincrement=True)
    zaman          = Column(DateTime, default=datetime.utcnow)
    otonom         = Column(Boolean)
    hedef_x        = Column(Integer)
    hedef_y        = Column(Integer)
    hedef_genislik = Column(Integer)
    hedef_yukseklik = Column(Integer)
    sunucuya_gonderildi = Column(Boolean, default=False)

# ─────────────────────────────────────────
# Kamikaze kayıtları
# ─────────────────────────────────────────
class Kamikaze(Base):
    __tablename__ = "kamikaze"

    id              = Column(Integer, primary_key=True, autoincrement=True)
    zaman           = Column(DateTime, default=datetime.utcnow)
    qr_metni        = Column(String)
    baslangic_zamani = Column(String)
    bitis_zamani    = Column(String)
    sunucuya_gonderildi = Column(Boolean, default=False)

# ─────────────────────────────────────────
# Rakip İHA konumları (sunucudan gelen)
# ─────────────────────────────────────────
class RakipKonum(Base):
    __tablename__ = "rakip_konum"

    id            = Column(Integer, primary_key=True, autoincrement=True)
    zaman         = Column(DateTime, default=datetime.utcnow)
    takim_no      = Column(Integer)
    enlem         = Column(Float)
    boylam        = Column(Float)
    irtifa        = Column(Float)
    hiz           = Column(Float)
    zaman_farki   = Column(Integer)

def veritabani_olustur():
    """Tabloları oluşturur — uygulama başında bir kez çağrılır."""
    Base.metadata.create_all(engine)
    print("[DB] Veritabanı hazır.")

if __name__ == "__main__":
    veritabani_olustur()