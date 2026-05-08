from __future__ import annotations

import datetime as dt
import ipaddress
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

from .config import settings
from .identity import ensure_state_dirs


class PKIManager:
    def __init__(self) -> None:
        ensure_state_dirs()

    def ensure_master_ca(self, master_ip: str) -> None:
        ca_cert = Path(settings.ca_cert_path)
        ca_key = Path(settings.ca_key_path)
        master_cert = Path(settings.master_cert_path)
        master_key = Path(settings.master_key_path)

        if not ca_cert.exists() or not ca_key.exists():
            ca_private_key = ec.generate_private_key(ec.SECP256R1())
            subject = x509.Name([
                x509.NameAttribute(NameOID.COMMON_NAME, "awg-master-ca"),
            ])
            cert = (
                x509.CertificateBuilder()
                .subject_name(subject)
                .issuer_name(subject)
                .public_key(ca_private_key.public_key())
                .serial_number(x509.random_serial_number())
                .not_valid_before(dt.datetime.now(dt.UTC) - dt.timedelta(minutes=1))
                .not_valid_after(dt.datetime.now(dt.UTC) + dt.timedelta(days=3650))
                .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
                .sign(ca_private_key, hashes.SHA256())
            )
            ca_key.write_bytes(
                ca_private_key.private_bytes(
                    encoding=serialization.Encoding.PEM,
                    format=serialization.PrivateFormat.TraditionalOpenSSL,
                    encryption_algorithm=serialization.NoEncryption(),
                )
            )
            ca_cert.write_bytes(cert.public_bytes(serialization.Encoding.PEM))

        if not master_cert.exists() or not master_key.exists():
            key = ec.generate_private_key(ec.SECP256R1())
            csr = self._build_csr("master-control", key, [master_ip])
            cert_pem = self.sign_node_csr(csr.public_bytes(serialization.Encoding.PEM), "master-control")
            master_key.write_bytes(
                key.private_bytes(
                    encoding=serialization.Encoding.PEM,
                    format=serialization.PrivateFormat.TraditionalOpenSSL,
                    encryption_algorithm=serialization.NoEncryption(),
                )
            )
            master_cert.write_bytes(cert_pem)

    def _load_ca(self) -> tuple[x509.Certificate, ec.EllipticCurvePrivateKey]:
        ca_cert = x509.load_pem_x509_certificate(Path(settings.ca_cert_path).read_bytes())
        ca_key = serialization.load_pem_private_key(Path(settings.ca_key_path).read_bytes(), password=None)
        return ca_cert, ca_key

    def _build_csr(self, common_name: str, key: ec.EllipticCurvePrivateKey, ips: list[str]) -> x509.CertificateSigningRequest:
        san_items: list[x509.GeneralName] = []
        for value in ips:
            value = value.strip()
            if not value:
                continue
            try:
                san_items.append(x509.IPAddress(ipaddress.ip_address(value)))
            except ValueError:
                san_items.append(x509.DNSName(value))
        builder = x509.CertificateSigningRequestBuilder().subject_name(
            x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, common_name)])
        )
        if san_items:
            builder = builder.add_extension(x509.SubjectAlternativeName(san_items), critical=False)
        return builder.sign(key, hashes.SHA256())

    def create_node_csr(self, node_id: str, node_ip: str, key_path: str) -> bytes:
        key = ec.generate_private_key(ec.SECP256R1())
        Path(key_path).write_bytes(
            key.private_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PrivateFormat.TraditionalOpenSSL,
                encryption_algorithm=serialization.NoEncryption(),
            )
        )
        csr = self._build_csr(node_id, key, [node_ip, node_id])
        return csr.public_bytes(serialization.Encoding.PEM)

    def sign_node_csr(self, csr_pem: bytes, common_name_fallback: str) -> bytes:
        ca_cert, ca_key = self._load_ca()
        csr = x509.load_pem_x509_csr(csr_pem)
        try:
            subject = csr.subject
        except Exception:
            subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, common_name_fallback)])

        builder = (
            x509.CertificateBuilder()
            .subject_name(subject)
            .issuer_name(ca_cert.subject)
            .public_key(csr.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(dt.datetime.now(dt.UTC) - dt.timedelta(minutes=1))
            .not_valid_after(dt.datetime.now(dt.UTC) + dt.timedelta(days=365))
            .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
            .add_extension(
                x509.ExtendedKeyUsage([ExtendedKeyUsageOID.CLIENT_AUTH, ExtendedKeyUsageOID.SERVER_AUTH]),
                critical=False,
            )
        )

        try:
            san = csr.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
            builder = builder.add_extension(san, critical=False)
        except Exception:
            pass

        cert = builder.sign(private_key=ca_key, algorithm=hashes.SHA256())
        return cert.public_bytes(serialization.Encoding.PEM)

    def read_ca_pem(self) -> bytes:
        return Path(settings.ca_cert_path).read_bytes()


pki_manager = PKIManager()
