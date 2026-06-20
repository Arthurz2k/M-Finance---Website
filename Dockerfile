# Utiliza a imagem oficial leve do Python
FROM python:3.11-slim

# Evita que o Python grave arquivos .pyc e bufeie o log
ENV PYTHONUNBUFFERED True

# Define o diretório de trabalho dentro do contêiner
WORKDIR /app

# Copia e instala as dependências
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copia o restante do código do projeto
COPY . .

# Comando para rodar o Gunicorn na porta definida pelo Cloud Run
CMD exec gunicorn --bind :$PORT --workers 1 --threads 8 --timeout 0 app:app