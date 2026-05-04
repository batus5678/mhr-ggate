"""
mhr-ggate | MITM Certificate Manager
Generates a local CA and per-domain certificates on the fly.
Browser must trust the CA cert (ca/ca.crt) for HTTPS to work.
"""

import os
import ssl
import datetime
import ipaddress
from pathlib import Path
from cryptography import x509
from cryptography.x509.oid import NameOID, ExtendedKeyUsageOID
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa

CA_DIR   = Path(__file__).parent / "ca"
CA_KEY   = CA_DIR / "ca.key"
CA_CERT  = CA_DIR / "ca.crt"
CERT_DIR = CA_DIR / "certs"


def _gen_key():
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


def ensure_ca():
    """Create the local CA if it doesn't exist yet."""
    CA_DIR.mkdir(exist_ok=True)
    CERT_DIR.mkdir(exist_ok=True)

    if CA_KEY.exists() and CA_CERT.exists():
        return

    print("[*] Generating MITM CA certificate...")
    key = _gen_key()
    name = x509.Name([
        x509.NameAttribute(NameOID.COMMON_NAME, "mhr-ggate Local CA"),
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, "mhr-ggate"),
    ])
    now = datetime.datetime.utcnow()
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now)
        .not_valid_after(now + datetime.timedelta(days=3650))
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .add_extension(x509.SubjectKeyIdentifier.from_public_key(key.public_key()), critical=False)
        .sign(key, hashes.SHA256())
    )

    CA_KEY.write_bytes(key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.TraditionalOpenSSL,
        serialization.NoEncryption(),
    ))
    CA_CERT.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    print(f"[+] CA cert saved to {CA_CERT}")
    print(f"[!] Install {CA_CERT} as a trusted root CA in your browser/system!")


def get_domain_cert(hostname: str) -> tuple[str, str]:
    """Return (cert_path, key_path) for a hostname, generating if needed."""
    ensure_ca()
    safe = hostname.replace("*", "_wildcard_")
    cert_file = CERT_DIR / f"{safe}.crt"
    key_file  = CERT_DIR / f"{safe}.key"

    if cert_file.exists() and key_file.exists():
        return str(cert_file), str(key_file)

    # Load CA
    ca_key = serialization.load_pem_private_key(CA_KEY.read_bytes(), password=None)
    ca_cert = x509.load_pem_x509_certificate(CA_CERT.read_bytes())

    key = _gen_key()
    now = datetime.datetime.utcnow()

    san_list = []
    try:
        san_list.append(x509.IPAddress(ipaddress.ip_address(hostname)))
    except ValueError:
        san_list.append(x509.DNSName(hostname))
        if not hostname.startswith("*."):
            san_list.append(x509.DNSName(f"*.{hostname}"))

    cert = (
        x509.CertificateBuilder()
        .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, hostname)]))
        .issuer_name(ca_cert.subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now)
        .not_valid_after(now + datetime.timedelta(days=825))
        .add_extension(x509.SubjectAlternativeName(san_list), critical=False)
        .add_extension(
            x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False
        )
        .sign(ca_key, hashes.SHA256())
    )

    key_file.write_bytes(key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.TraditionalOpenSSL,
        serialization.NoEncryption(),
    ))
    cert_file.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    return str(cert_file), str(key_file)


def make_ssl_context(hostname: str) -> ssl.SSLContext:
    """Return a server-side SSLContext with a fake cert for hostname."""
    cert_file, key_file = get_domain_cert(hostname)
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(cert_file, key_file)
    return ctx
