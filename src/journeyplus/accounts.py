"""Small local account store; server sessions contain only a random token hash."""
from datetime import timedelta
from hashlib import scrypt,sha256
import hmac,secrets
from uuid import UUID,uuid4
from sqlalchemy import String,Uuid,DateTime,Integer,ForeignKey,select
from sqlalchemy.orm import Mapped,mapped_column
from journeyplus.models import Base,now_utc
from journeyplus.user_scope import OWNER_ID

class UserAccount(Base):
    __tablename__='user_accounts'
    id:Mapped[UUID]=mapped_column(Uuid,primary_key=True,default=uuid4)
    username:Mapped[str]=mapped_column(String(100),unique=True)
    password_hash:Mapped[str]=mapped_column(String(300))
    current_workspace_id:Mapped[UUID|None]=mapped_column(Uuid,nullable=True)
    failed_logins:Mapped[int]=mapped_column(Integer,default=0)
    locked_until:Mapped[object|None]=mapped_column(DateTime(timezone=True),nullable=True)
    created_at:Mapped[object]=mapped_column(DateTime(timezone=True),default=now_utc)

class LoginSession(Base):
    __tablename__='login_sessions'
    token_hash:Mapped[str]=mapped_column(String(64),primary_key=True)
    user_id:Mapped[UUID]=mapped_column(ForeignKey('user_accounts.id',ondelete='CASCADE'),index=True)
    expires_at:Mapped[object]=mapped_column(DateTime(timezone=True))

def password_hash(password):
    if not 12<=len(password)<=512:raise ValueError('Password must contain 12..512 characters')
    salt=secrets.token_bytes(16)
    hashed=scrypt(password.encode(),salt=salt,n=16384,r=8,p=1,dklen=32)
    return 'scrypt$'+salt.hex()+'$'+hashed.hex()

def verify_password(password,encoded):
    try:
        kind,salt,expected=encoded.split('$')
        if kind!='scrypt' or len(password)>512:return False
        actual=scrypt(password.encode(),salt=bytes.fromhex(salt),n=16384,r=8,p=1,dklen=32)
        return hmac.compare_digest(actual.hex(),expected)
    except (ValueError,TypeError):return False

def token_hash(token):return sha256(token.encode()).hexdigest()

def create_account(factory,username,password,*,identity=None):
    username=username.strip().casefold()
    if not username or len(username)>100:raise ValueError('Invalid username')
    with factory.begin() as s:
        row=UserAccount(id=identity or uuid4(),username=username,password_hash=password_hash(password))
        s.add(row);s.flush();return row.id

def main():
    import argparse,getpass
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from journeyplus.config import Settings
    parser=argparse.ArgumentParser(description='Create a JourneyPlus account or set its password')
    parser.add_argument('username');parser.add_argument('--owner',action='store_true',help='Initialize the original data owner')
    parser.add_argument('--reset-password',action='store_true')
    args=parser.parse_args();password=getpass.getpass('Password (12+ characters): ')
    if password!=getpass.getpass('Confirm password: '):raise SystemExit('Passwords differ')
    factory=sessionmaker(create_engine(Settings.from_env().database_url))
    with factory.begin() as s:
        row=s.scalar(select(UserAccount).where(UserAccount.id==OWNER_ID)) if args.owner else s.scalar(select(UserAccount).where(UserAccount.username==args.username.casefold()))
        if row:
            if not args.reset_password:raise SystemExit('Account exists; use --reset-password')
            row.password_hash=password_hash(password);row.failed_logins=0;row.locked_until=None
            from sqlalchemy import delete
            s.execute(delete(LoginSession).where(LoginSession.user_id==row.id))
        else:s.add(UserAccount(id=OWNER_ID if args.owner else uuid4(),username=args.username.strip().casefold(),password_hash=password_hash(password)))
    print('Account ready')

if __name__=='__main__':main()
