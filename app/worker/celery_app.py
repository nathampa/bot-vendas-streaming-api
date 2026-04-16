from celery import Celery
from app.core.config import settings

broker_url = settings.CELERY_BROKER_URL or "memory://"
backend_url = settings.CELERY_BROKER_URL or "cache+memory://"

# 1. Cria a instância do Celery
# O primeiro argumento "worker" é o nome da app.
# O 'broker' e 'backend' usam a URL do Redis que definimos no .env
celery_app = Celery(
    "worker",
    broker=broker_url,
    backend=backend_url,
)

# 2. Configurações (opcionais, mas boas)
celery_app.conf.update(
    task_track_started=True,
    result_expires=3600, # Tempo que os resultados das tarefas são guardados
)

# 3. Auto-descoberta de Tarefas
# Diz ao Celery para procurar automaticamente por ficheiros 'tasks.py'
# dentro dos módulos listados.
celery_app.autodiscover_tasks(
    ["app.worker"] # Vai procurar por 'app.worker.tasks'
)

# (Este ficheiro agora exporta com sucesso a variável 'celery_app')
