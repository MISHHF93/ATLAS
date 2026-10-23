"""Policy integrity: ed25519 detached signature OR sha256 pin. Fail closed.

Modes (first match wins):
  1. ed25519: config/risk_policy.yaml.sig (base64 signature) verified against
     config/policy_signing_pubkey.pem (PEM public key). The private key must
     live OUTSIDE the repo (owner's device / vault); see `atlas-sign-policy`.
  2. sha256 pin: config/risk_policy.yaml.sha256 contains the hex digest.
If neither file exists => error (unsigned policy rejected).
The repo ships a sha256 pin for development (no private key anywhere).
"""
from __future__ import annotations

import base64
import hashlib
from pathlib import Path

SIG = "risk_policy.yaml.sig"
PUB = "policy_signing_pubkey.pem"
PIN = "risk_policy.yaml.sha256"


def verify_policy(config_dir: Path) -> list[str]:
    raw = (config_dir / "risk_policy.yaml").read_bytes()
    sig, pub, pin = config_dir / SIG, config_dir / PUB, config_dir / PIN
    if sig.exists() or pub.exists():
        if not (sig.exists() and pub.exists()):
            return ["policy signature: both risk_policy.yaml.sig and policy_signing_pubkey.pem are required"]
        try:
            from cryptography.exceptions import InvalidSignature
            from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
            from cryptography.hazmat.primitives.serialization import load_pem_public_key
            key = load_pem_public_key(pub.read_bytes())
            if not isinstance(key, Ed25519PublicKey):
                return ["policy signature: public key is not ed25519"]
            key.verify(base64.b64decode(sig.read_text().strip()), raw)
            return []
        except InvalidSignature:
            return ["policy signature: ed25519 signature INVALID for risk_policy.yaml"]
        except Exception as e:  # missing lib, bad encoding, ...
            return [f"policy signature: verification error {e!r}"]
    if pin.exists():
        want = pin.read_text().split()[0].strip().lower() if pin.read_text().strip() else ""
        got = hashlib.sha256(raw).hexdigest()
        return [] if want == got else [f"policy signature: sha256 pin mismatch (pinned {want[:12]}…, actual {got[:12]}…)"]
    return ["policy signature: risk_policy.yaml is unsigned (no .sig/.pem or .sha256 pin)"]


def sign_policy_main(argv: list[str] | None = None) -> int:
    """atlas-sign-policy <config_dir> <path-to-ed25519-private-key.pem (outside repo)>"""
    import sys
    from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat, load_pem_private_key
    argv = sys.argv[1:] if argv is None else argv
    d, keyp = Path(argv[0]), Path(argv[1])
    key = load_pem_private_key(keyp.read_bytes(), password=None)
    (d / SIG).write_text(base64.b64encode(key.sign((d / "risk_policy.yaml").read_bytes())).decode())
    (d / PUB).write_bytes(key.public_key().public_bytes(Encoding.PEM, PublicFormat.SubjectPublicKeyInfo))
    print(f"signed {d / 'risk_policy.yaml'}")
    return 0
