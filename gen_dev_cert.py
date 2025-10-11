# gen_dev_cert.py
from datetime import datetime, timedelta
import ipaddress, os
from cryptography import x509
from cryptography.x509.oid import NameOID
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa

CERT_FILE = "cert.pem"
KEY_FILE = "key.pem"

# Solo si no existen
if not (os.path.exists(CERT_FILE) and os.path.exists(KEY_FILE)):
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)

    subject = issuer = x509.Name([
        x509.NameAttribute(NameOID.COUNTRY_NAME, "MX"),
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, "IHOP Dev"),
        x509.NameAttribute(NameOID.COMMON_NAME, "localhost"),
    ])

    alt_names = x509.SubjectAlternativeName([
        x509.DNSName("localhost"),
        x509.IPAddress(ipaddress.IPv4Address("127.0.0.1")),
    ])

    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(datetime.utcnow() - timedelta(days=1))
        .not_valid_after(datetime.utcnow() + timedelta(days=365))
        .add_extension(alt_names, critical=False)
        .sign(private_key=key, algorithm=hashes.SHA256())
    )

    with open(KEY_FILE, "wb") as f:
        f.write(
            key.private_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PrivateFormat.TraditionalOpenSSL,
                encryption_algorithm=serialization.NoEncryption(),
            )
        )

    with open(CERT_FILE, "wb") as f:
        f.write(cert.public_bytes(serialization.Encoding.PEM))

print("OK: cert.pem y key.pem listos")
