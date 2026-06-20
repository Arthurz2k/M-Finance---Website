from flask import Flask, render_template, request, jsonify, redirect, url_for, session
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
import os
import psycopg2
from dotenv import load_dotenv
import hashlib
import re
from PIL import Image
import pdfplumber
from google import genai  
import json

load_dotenv()

# Inicializa o cliente do Gemini utilizando a nova biblioteca padrão
client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))

app = Flask(__name__)
app.secret_key = os.getenv('SECRET_KEY')
app.config['UPLOAD_FOLDER'] = 'uploads'
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

# -------------------------------------------------------------------
# CONFIGURAÇÃO DO BANCO DE DADOS
# -------------------------------------------------------------------
def get_db_connection():
    return psycopg2.connect(os.getenv('DATABASE_URL'))

def setup_database():
    conn = get_db_connection()
    cur = conn.cursor()
    
    cur.execute('''
        CREATE TABLE IF NOT EXISTS usuarios (
            id SERIAL PRIMARY KEY,
            email VARCHAR(255) UNIQUE NOT NULL,
            senha VARCHAR(255) NOT NULL
        )
    ''')
    
    cur.execute('''
        CREATE TABLE IF NOT EXISTS notas_salvas (
            id SERIAL PRIMARY KEY,
            hash_arquivo VARCHAR(255) UNIQUE NOT NULL,
            nome_arquivo VARCHAR(255),
            tipo VARCHAR(50),
            valor VARCHAR(50),
            data_upload TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    cur.execute("SELECT * FROM usuarios WHERE email = 'admin@marildo.com'")
    if not cur.fetchone():
        hashed_pw = generate_password_hash('Admin123!')
        cur.execute("INSERT INTO usuarios (email, senha) VALUES (%s, %s)", ('admin@marildo.com', hashed_pw))
        
    conn.commit()
    cur.close()
    conn.close()

try:
    setup_database()
    print("Banco de dados Neon conectado e configurado com sucesso!")
except Exception as e:
    print(f"Erro ao conectar no banco: {e}")

# -------------------------------------------------------------------
# ROTAS DE AUTENTICAÇÃO
# -------------------------------------------------------------------
@app.route('/', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute('SELECT senha FROM usuarios WHERE email = %s', (email,))
        user = cur.fetchone()
        cur.close()
        conn.close()
        if user and check_password_hash(user[0], password):
            session['usuario_logado'] = email
            return redirect(url_for('dashboard'))
        else:
            return render_template('login.html', error="E-mail ou senha incorretos.")
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

# -------------------------------------------------------------------
# ROTAS DAS TELAS (BUSCANDO DO BANCO DE DADOS NEON)
# -------------------------------------------------------------------
@app.route('/dashboard')
def dashboard():
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT id, nome_arquivo, tipo, valor, TO_CHAR(data_upload, 'DD/MM/YYYY HH24:MI') FROM notas_salvas ORDER BY id DESC LIMIT 5")
    recentes = cur.fetchall()
    cur.close()
    conn.close()
    return render_template('index.html', notas=recentes)

@app.route('/notas')
def notas():
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT id, nome_arquivo, tipo, valor, TO_CHAR(data_upload, 'DD/MM/YYYY') FROM notas_salvas ORDER BY id DESC")
    todas_notas = cur.fetchall()
    cur.close()
    conn.close()
    return render_template('notas.html', notas=todas_notas)

# -------------------------------------------------------------------
# ROTA PARA DELETAR UMA NOTA
# -------------------------------------------------------------------
@app.route('/delete/<int:id>', methods=['POST'])
def delete_nota(id):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("DELETE FROM notas_salvas WHERE id = %s", (id,))
    conn.commit()
    cur.close()
    conn.close()
    return redirect(request.referrer)

# -------------------------------------------------------------------
# MOTOR DE UPLOAD (ATUALIZADO COM O NOVO SDK GOOGLE-GENAI)
# -------------------------------------------------------------------
@app.route('/upload', methods=['POST'])
def upload_file():
    if 'file' not in request.files:
        return jsonify({'error': 'Nenhum arquivo enviado'}), 400
    file = request.files['file']
    if file.filename == '':
        return jsonify({'error': 'Nome de arquivo vazio'}), 400
        
    if file:
        filename = secure_filename(file.filename)
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        file.save(filepath)

        with open(filepath, "rb") as f:
            file_hash = hashlib.sha256(f.read()).hexdigest()

        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute('SELECT nome_arquivo FROM notas_salvas WHERE hash_arquivo = %s', (file_hash,))
        duplicado = cur.fetchone()
        
        if duplicado:
            cur.close()
            conn.close()
            os.remove(filepath)
            return jsonify({'error': f'Atenção: Este documento já foi processado anteriormente como "{duplicado[0]}"!'})

        try:
            valor_encontrado = "Não identificado"
            tipo_doc = "Comprovante"

            # --- 1. SE FOR ARQUIVO PDF DIGITAL ---
            if filename.lower().endswith('.pdf'):
                tipo_doc = "PDF"
                texto_extraido = ""
                with pdfplumber.open(filepath) as pdf:
                    for page in pdf.pages:
                        page_text = page.extract_text()
                        if page_text:
                            texto_extraido += page_text + "\n"
                
                if texto_extraido:
                    texto_limpo = texto_extraido.replace('\n', ' ').replace('  ', ' ')
                    padrao_valor = r'(?:R\$|VALOR|PAGO|TOTAL|VALOR PAGO|VALOR DO PIX|IMPORTANCIA PAGA)\s*[:\-]?\s*(?:R\$|R \$)?\s*(\d{1,3}(?:\.\d{3})*,\d{2})'
                    match = re.search(padrao_valor, texto_limpo, re.IGNORECASE)
                    
                    if match:
                        valor_encontrado = match.group(1)
                    else:
                        fallback_match = re.findall(r'R\$\s*(\d{1,3}(?:\.\d{3})*,\d{2})', texto_limpo, re.IGNORECASE)
                        if fallback_match:
                            valor_encontrado = fallback_match[-1]

            # --- 2. SE FOR IMAGEM (PNG, JPG, JPEG) -> NOVO FORMATO DO CLIENTE GEMINI ---
            else:
                img = Image.open(filepath)
                
                prompt = (
                    "Analise este comprovante financeiro brasileiro e extraia o VALOR total da transação "
                    "e o TIPO do documento (ex: PIX, Boleto, Extrato, NFC-e).\n"
                    "Responda estritamente em formato JSON, usando exatamente esta estrutura: "
                    '{"valor": "40,00", "tipo": "PIX"}. '
                    'Se o valor não for identificado de forma clara na imagem, retorne "Não identificado" no campo valor.'
                )
                
                # Mudamos aqui para o 'gemini-2.5-flash', o modelo padrão atual da biblioteca
                response = client.models.generate_content(
                    model='gemini-2.5-flash', 
                    contents=[prompt, img]
                )
                
                # Limpa possíveis marcações de markdown do JSON
                texto_resposta = response.text.strip()
                if texto_resposta.startswith("```"):
                    texto_resposta = texto_resposta.replace("```json", "").replace("```", "").strip()
                
                dados_ia = json.loads(texto_resposta)
                valor_encontrado = dados_ia.get("valor", "Não identificado")
                tipo_doc = dados_ia.get("tipo", "Imagem")

            # Grava as informações finais no banco de dados
            cur.execute('INSERT INTO notas_salvas (hash_arquivo, nome_arquivo, tipo, valor) VALUES (%s, %s, %s, %s)', 
                        (file_hash, filename, tipo_doc, valor_encontrado))
            conn.commit()

        except Exception as e:
            print(f"Erro no processamento da IA: {e}")
            return jsonify({'error': f'Falha Crítica ({type(e).__name__}): A inteligência artificial não conseguiu processar os dados desta imagem.'})
        finally:
            cur.close()
            conn.close()
            if os.path.exists(filepath):
                os.remove(filepath)

        return jsonify({'message': 'Sucesso', 'valor': valor_encontrado, 'tipo': tipo_doc})

if __name__ == '__main__':
    app.run(debug=True)