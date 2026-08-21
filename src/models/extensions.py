import os

from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_wtf.csrf import CSRFProtect

db = SQLAlchemy()
migrate = Migrate()
csrf = CSRFProtect()

#: Speicher fuer die Rate-Limit-Zaehler.
#:
#: Standard bleibt bewusst memory://. Das ist PROZESSLOKAL: bei mehreren
#: Gunicorn-Workern fuehrt jeder Worker eigene Zaehler, und ein Neustart
#: setzt sie zurueck. Fuer sich genommen ist das also ein schwacher
#: Schutz.
#:
#: Die harte Obergrenze uebernimmt deshalb nginx mit einer Shared-Memory-
#: Zone (limit_req_zone, siehe ops/nginx-footsim.conf.reference). Die
#: zaehlt einmal fuer alle Worker, ueberlebt Neustarts der Anwendung und
#: nutzt $binary_remote_addr - also die echte TCP-Adresse statt eines
#: faelschbaren Headers. Flask-Limiter bleibt daneben als
#: Defense-in-Depth mit Kenntnis der einzelnen Route.
#:
#: Ein geteilter Speicher (z. B. Redis) ist damit NICHT erforderlich und
#: wird bewusst nicht vorausgesetzt - er waere ein zusaetzlicher Dienst
#: fuer einen Nutzen, den nginx hier bereits liefert. Wer trotzdem einen
#: hat, setzt FOOTSIM_RATELIMIT_STORAGE_URI und bekommt worker-
#: uebergreifende Zaehler ohne Codeaenderung.
RATELIMIT_STORAGE_URI = os.environ.get("FOOTSIM_RATELIMIT_STORAGE_URI") or "memory://"

limiter = Limiter(
    key_func=get_remote_address,
    default_limits=["1000 per day", "100 per hour"],
    storage_uri=RATELIMIT_STORAGE_URI,
)
