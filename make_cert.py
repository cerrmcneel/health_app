"""Generate a self-signed TLS certificate so the camera works off localhost.

Browsers only expose getUserMedia on a secure context. http://192.168.x.x is not
one, so the capture page cannot open the camera over plain HTTP on your LAN --
this script produces the cert that fixes that.

    python make_cert.py 192.168.1.50
    uvicorn app.main:app --host 0.0.0.0 --port 8443 \
        --ssl-keyfile certs/key.pem --ssl-certfile certs/cert.pem

The certificate is self-signed, so the phone will show a warning once. Accept it
(Advanced -> Proceed) and the camera becomes available. Requires `cryptography`:

    pip install cryptography
"""
import datetime
import ipaddress
import socket
import sys
from pathlib import Path

try:
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID
except ImportError:
    sys.exit("Missing dependency. Run: pip install cryptography")

OUT = Path(__file__).parent / "certs"


def local_ip() -> str:
    """Best-effort LAN IP. No packets are actually sent to the probe address."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


def main() -> None:
    hosts = sys.argv[1:] or [local_ip()]
    OUT.mkdir(exist_ok=True)

    names: list[x509.GeneralName] = [
        x509.DNSName("localhost"),
        x509.IPAddress(ipaddress.ip_address("127.0.0.1")),
    ]
    for host in hosts:
        try:
            names.append(x509.IPAddress(ipaddress.ip_address(host)))
        except ValueError:
            names.append(x509.DNSName(host))

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, hosts[0])])
    now = datetime.datetime.now(datetime.timezone.utc)

    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(days=1))
        .not_valid_after(now + datetime.timedelta(days=825))
        .add_extension(x509.SubjectAlternativeName(names), critical=False)
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .sign(key, hashes.SHA256())
    )

    (OUT / "key.pem").write_bytes(key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.TraditionalOpenSSL,
        encryption_algorithm=serialization.NoEncryption(),
    ))
    (OUT / "cert.pem").write_bytes(cert.public_bytes(serialization.Encoding.PEM))

    print(f"Wrote {OUT / 'cert.pem'} and {OUT / 'key.pem'}")
    print(f"Valid for: {', '.join(str(n.value) for n in names)}")
    print("\nStart the server with TLS:")
    print("  uvicorn app.main:app --host 0.0.0.0 --port 8443 \\")
    print("    --ssl-keyfile certs/key.pem --ssl-certfile certs/cert.pem")
    print(f"\nThen open https://{hosts[0]}:8443 on your phone and accept the warning.")


if __name__ == "__main__":
    main()
