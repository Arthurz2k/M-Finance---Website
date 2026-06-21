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

    # ---> ADICIONE ESTE BLOCO AQUI <---
    # Força a criação da coluna 'tag' caso a tabela seja antiga e ainda não a tenha
    try:
        cur.execute('''
            ALTER TABLE notas_salvas 
            ADD COLUMN IF NOT EXISTS tag VARCHAR(50) DEFAULT 'Outros';
        ''')
    except Exception as e:
        print(f"Aviso ao alterar tabela: {e}")
    # -----------------------------------
    
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

# A rota agora só aceita POST (envio de formulário)
@app.route('/register', methods=['POST'])
def register():
    email = request.form.get('email')
    password = request.form.get('password')
    
    conn = get_db_connection()
    cur = conn.cursor()
    
    # Verifica se o e-mail já existe
    cur.execute('SELECT id FROM usuarios WHERE email = %s', (email,))
    if cur.fetchone():
        cur.close()
        conn.close()
        # Devolve para o login mostrando o erro
        return render_template('login.html', error="Este e-mail já está em uso.")
        
    # Cria a senha criptografada e salva o usuário
    hashed_pw = generate_password_hash(password)
    cur.execute("INSERT INTO usuarios (email, senha) VALUES (%s, %s)", (email, hashed_pw))
    conn.commit()
    
    cur.close()
    conn.close()
    
    # Devolve para o login mostrando a mensagem de sucesso!
    return render_template('login.html', success="Conta criada com sucesso! Faça o login.")

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
            # Captura a tag que o usuário selecionar na tela (se existir o campo)
            tag_selecionada = request.form.get('tag', 'Outros')

            # Grava as informações finais no banco de dados INCLUINDO A TAG
            cur.execute('INSERT INTO notas_salvas (hash_arquivo, nome_arquivo, tipo, valor, tag) VALUES (%s, %s, %s, %s, %s)', 
                        (file_hash, filename, tipo_doc, valor_encontrado, tag_selecionada))
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

@app.route('/api/nota/<int:nota_id>')
def obter_detalhes_nota(nota_id):
    conn = get_db_connection()
    cur = conn.cursor()
    # Busca a nota específica no banco
    cur.execute("SELECT id, nome_arquivo, tipo, valor, tag, TO_CHAR(data_upload, 'DD/MM/YYYY HH24:MI') FROM notas_salvas WHERE id = %s", (nota_id,))
    nota = cur.fetchone()
    cur.close()
    conn.close()
    
    if nota:
        return jsonify({
            "id": nota[0],
            "nome_arquivo": nota[1],
            "tipo": nota[2],
            "valor": nota[3],
            "tag": nota[4],
            "data": nota[5]
        })
    return jsonify({"erro": "Nota não encontrada"}), 404

if __name__ == '__main__':
    app.run(debug=True)