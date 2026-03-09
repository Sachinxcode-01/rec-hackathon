from pywebpush import webpush, WebPushException
import json

# Generate VAPID key pair
# This can be done as a one-time step.
# For convenience, I will generate them and print them.

import os
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
import base64

def generate_vapid_keys():
    private_key = ec.generate_private_key(ec.SECP256R1())
    public_key = private_key.public_key()
    
    # Export public key
    public_key_bytes = public_key.public_bytes(
        encoding=serialization.Encoding.X962,
        format=serialization.PublicFormat.UncompressedPoint
    )
    
    # Export private key to PEM
    private_key_bytes = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption()
    )
    
    # B64-encode for easy environment variable storage
    # Actually, pywebpush expects it a bit differently.
    # It takes private_key as a PEM string or a filepath.
    
    vapid_public_key = base64.urlsafe_b64encode(public_key_bytes).decode('utf-8').rstrip('=')
    
    # For private key, let's get the raw d parameter or keep as PEM.
    # PEM is fine for pywebpush.
    vapid_private_key_pem = private_key_bytes.decode('utf-8')
    
    return vapid_public_key, vapid_private_key_pem

print("--- GENERATING VAPID KEYS ---")
pub, priv = generate_vapid_keys()
print(f"VAPID_PUBLIC_KEY={pub}")
print(f"VAPID_PRIVATE_KEY={priv}")
