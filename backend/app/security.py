from __future__ import annotations
import base64, hashlib, hmac, json, os, time
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session
from .database import get_db
from .models import User
from .settings import settings

bearer=HTTPBearer(auto_error=False)

def _b64(data:bytes)->str: return base64.urlsafe_b64encode(data).decode().rstrip('=')
def _unb64(data:str)->bytes: return base64.urlsafe_b64decode(data+'='*(-len(data)%4))

def hash_password(password:str)->str:
    salt=os.urandom(16); digest=hashlib.pbkdf2_hmac('sha256',password.encode(),salt,310_000)
    return f'pbkdf2_sha256$310000${_b64(salt)}${_b64(digest)}'

def verify_password(password:str,hashed:str)->bool:
    try:
        _,rounds,salt,digest=hashed.split('$'); actual=hashlib.pbkdf2_hmac('sha256',password.encode(),_unb64(salt),int(rounds)); return hmac.compare_digest(actual,_unb64(digest))
    except Exception: return False

def create_access_token(user:User)->str:
    payload={'sub':str(user.id),'role':user.role,'exp':int(time.time())+settings.access_token_minutes*60}
    body=_b64(json.dumps(payload,separators=(',',':')).encode()); sig=_b64(hmac.new(settings.secret_key.encode(),body.encode(),hashlib.sha256).digest()); return f'{body}.{sig}'

def _decode(token:str)->dict:
    try:
        body,sig=token.split('.',1); expected=_b64(hmac.new(settings.secret_key.encode(),body.encode(),hashlib.sha256).digest())
        if not hmac.compare_digest(sig,expected): raise ValueError
        payload=json.loads(_unb64(body));
        if int(payload['exp'])<int(time.time()): raise ValueError
        return payload
    except Exception as exc: raise HTTPException(status_code=401,detail='Невалидна или изтекла сесия') from exc

def get_current_user(credentials:HTTPAuthorizationCredentials|None=Depends(bearer),db:Session=Depends(get_db))->User:
    if credentials is None: raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,detail='Необходим е вход в системата')
    payload=_decode(credentials.credentials)
    user=db.scalar(select(User).where(User.id==int(payload['sub']),User.is_active.is_(True)))
    if not user: raise HTTPException(status_code=401,detail='Потребителят не е намерен')
    return user
