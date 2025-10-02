from flask import Flask, request, jsonify, session
import sqlite3
import requests
import json
import re
from datetime import datetime
from flask import send_from_directory
import os
import hashlib
import csv

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'dev-key-para-render')

# Configurações para Render
DEEPSEEK_API_KEY = os.environ.get('DEEPSEEK_API_KEY', 'sua-chave-aqui')
DEEPSEEK_API_URL = "https://api.deepseek.com/v1/chat/completions"

# Configuração do banco de dados - usar path absoluto no Render
DB_NAME = os.path.join(os.path.dirname(__file__), "mensagens_projetos.db")

# Configurar diretório estático
app.static_folder = 'static'
app.static_url_path = '/static'

# Carregar projetos do CSV (sem pandas)
def carregar_projetos():
    """Carrega a lista de projetos do arquivo CSV"""
    try:
        csv_path = os.path.join(os.path.dirname(__file__), 'projetos.csv')
        projetos = []
        
        if os.path.exists(csv_path):
            with open(csv_path, 'r', encoding='utf-8') as file:
                reader = csv.DictReader(file)
                for row in reader:
                    projetos.append({
                        'id': str(row['ID']),
                        'nome': row['Projeto'],
                        'display': f"{row['ID']} - {row['Projeto']}"
                    })
            print(f"Projetos carregados: {len(projetos)}")
            return projetos
        else:
            print("Arquivo projetos.csv não encontrado. Criando lista vazia.")
            # Criar um arquivo CSV exemplo se não existir
            with open(csv_path, 'w', encoding='utf-8') as file:
                file.write("ID,Projeto\n10001,Projeto Alpha\n10002,Projeto Beta\n10003,Projeto Gama\n")
            return [
                {'id': '10001', 'nome': 'Projeto Alpha', 'display': '10001 - Projeto Alpha'},
                {'id': '10002', 'nome': 'Projeto Beta', 'display': '10002 - Projeto Beta'},
                {'id': '10003', 'nome': 'Projeto Gama', 'display': '10003 - Projeto Gama'}
            ]
    except Exception as e:
        print(f"Erro ao carregar projetos do CSV: {e}")
        return []

class DBAnalyzer:
    def __init__(self, api_key, db_file_path):
        self.api_key = api_key
        self.db_file_path = db_file_path
        self.api_url = "https://api.deepseek.com/v1/chat/completions"
        self.headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
    
    def extract_db_schema(self, projeto_id=None):
        """Extrai o schema completo do banco de dados SQLite"""
        try:
            conn = sqlite3.connect(self.db_file_path)
            cursor = conn.cursor()
            
            # Obtém todas as tabelas
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
            tables = cursor.fetchall()
            
            schema = "SCHEMA DO BANCO DE DADOS:\n\n"
            
            for table in tables:
                table_name = table[0]
                schema += f"TABELA: {table_name}\n"
                
                # Obtém a estrutura da tabela
                cursor.execute(f"PRAGMA table_info({table_name})")
                columns = cursor.fetchall()
                
                for column in columns:
                    schema += f"  - {column[1]} ({column[2]})"
                    if column[5] == 1:
                        schema += " PRIMARY KEY"
                    schema += "\n"
                
                schema += "\n"
            
            conn.close()
            return schema
            
        except Exception as e:
            print(f"Erro ao extrair schema do banco de dados: {e}")
            return ""
    
    def extract_data_samples(self, projeto_id=None):
        """Extrai amostras de dados de cada tabela para análise"""
        try:
            conn = sqlite3.connect(self.db_file_path)
            cursor = conn.cursor()
            
            # Obtém todas as tabelas
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
            tables = cursor.fetchall()
            
            data_samples = "AMOSTRAS DE DADOS:\n\n"
            
            for table in tables:
                table_name = table[0]
                
                # Constrói a query com filtro de projeto se especificado
                where_clause = f" WHERE projeto = '{projeto_id}'" if projeto_id else ""
                query = f"SELECT * FROM {table_name}{where_clause} LIMIT 5"
                
                try:
                    cursor.execute(query)
                    rows = cursor.fetchall()
                    
                    # Obtém os nomes das colunas
                    cursor.execute(f"PRAGMA table_info({table_name})")
                    columns = [col[1] for col in cursor.fetchall()]
                    
                    if rows:
                        data_samples += f"TABELA: {table_name}\n"
                        data_samples += f"COLUNAS: {', '.join(columns)}\n"
                        data_samples += f"DADOS ({len(rows)} linhas):\n"
                        
                        for row in rows:
                            data_samples += f"  {row}\n"
                        data_samples += "\n"
                    else:
                        data_samples += f"TABELA: {table_name} - SEM DADOS{'(para este projeto)' if projeto_id else ''}\n\n"
                    
                except Exception as e:
                    continue
            
            conn.close()
            return data_samples
            
        except Exception as e:
            print(f"Erro ao extrair amostras de dados: {e}")
            return ""
    
    def execute_query(self, query: str):
        """Executa uma query SQL e retorna os resultados (sem pandas)"""
        try:
            conn = sqlite3.connect(self.db_file_path)
            cursor = conn.cursor()
            cursor.execute(query)
            
            # Obter nomes das colunas
            if cursor.description:
                columns = [description[0] for description in cursor.description]
                
                # Converter para lista de dicionários
                results = []
                for row in cursor.fetchall():
                    results.append(dict(zip(columns, row)))
                
                conn.close()
                return results
            else:
                # Para queries como INSERT, UPDATE, DELETE
                conn.close()
                return [{'affected_rows': cursor.rowcount}]
                
        except Exception as e:
            print(f"Erro ao executar query: {e}")
            return []
    
    def ask_question(self, question, projeto_id=None):
        # Extrai schema e amostras filtradas pelo projeto
        schema_content = self.extract_db_schema()
        data_samples = self.extract_data_samples(projeto_id)
        
        # Verifica se a pergunta requer consulta a dados específicos
        query_result = ""
        
        # Adiciona filtro de projeto às consultas se especificado
        where_clause = f" WHERE projeto = '{projeto_id}'" if projeto_id else ""
        
        # Exemplos de perguntas que podem requerer consultas específicas
        if "quantas vezes" in question.lower() and "categoria" in question.lower():
            words = question.lower().split()
            categoria = None
            
            for i, word in enumerate(words):
                if word == "categoria" and i + 1 < len(words):
                    categoria = words[i + 1]
                    break
            
            if categoria:
                query = f"SELECT COUNT(*) as count FROM mensagens WHERE categoria = '{categoria}'{where_clause}"
                result = self.execute_query(query)
                if result and 'count' in result[0]:
                    query_result = f"\nRESULTADO DA CONSULTA: A categoria '{categoria}' aparece {result[0]['count']} vezes{(' no projeto selecionado' if projeto_id else '')}.\n"
        
        elif "quantas" in question.lower() and "mensagens" in question.lower():
            query = f"SELECT COUNT(*) as total FROM mensagens{where_clause}"
            result = self.execute_query(query)
            if result and 'total' in result[0]:
                query_result = f"\nRESULTADO DA CONSULTA: Existem {result[0]['total']} mensagens{(' neste projeto' if projeto_id else ' no total')}.\n"
        
        elif "categorias" in question.lower() and "existem" in question.lower():
            query = f"SELECT DISTINCT categoria, COUNT(*) as count FROM mensagens{where_clause} GROUP BY categoria ORDER BY count DESC"
            result = self.execute_query(query)
            if result:
                query_result = f"\nRESULTADO DA CONSULTA: Distribuição por categorias{(' no projeto selecionado' if projeto_id else '')}:\n"
                for item in result:
                    query_result += f"  - {item['categoria']}: {item['count']} mensagens\n"
        
        elif "lessons learned" in question.lower() or "lições aprendidas" in question.lower():
            query = f"SELECT COUNT(*) as count FROM mensagens WHERE lesson_learned = 'sim'{where_clause}"
            result = self.execute_query(query)
            if result and 'count' in result[0]:
                query_result = f"\nRESULTADO DA CONSULTA: Existem {result[0]['count']} Lessons Learned{(' neste projeto' if projeto_id else ' no total')}.\n"
        
        # Prepara o prompt para a API
        projeto_info = f"\nPROJETO SELECIONADO: {projeto_id}\n" if projeto_id else ""
        
        prompt = f"""
        Baseado no schema do banco de dados e nas amostras de dados fornecidas, responda a pergunta abaixo.
        Use também as informações dos resultados de consulta quando disponíveis.

        {projeto_info}
        {schema_content}
        {data_samples}
        {query_result}

        PERGUNTA:
        {question}

        RESPOSTA (seja claro e direto, baseando-se nos dados disponíveis):
        """
        
        payload = {
            "model": "deepseek-chat",
            "messages": [
                {"role": "system", "content": "Você é um assistente especializado em análise de bancos de dados SQL. Responda sempre em português de forma clara e direta, baseando-se apenas nos dados fornecidos."},
                {"role": "user", "content": prompt}
            ],
            "temperature": 0.1,
            "max_tokens": 2000
        }
        
        try:
            print("Consultando a API DeepSeek..." + (f" Projeto: {projeto_id}" if projeto_id else ""))
            response = requests.post(self.api_url, headers=self.headers, json=payload, timeout=30)
            response.raise_for_status()
            result = response.json()
            return result['choices'][0]['message']['content']
        except requests.exceptions.RequestException as e:
            return f"Erro na requisição à API: {e}"
        except KeyError:
            return "Erro: Resposta inesperada da API."

def inicializar_banco():
    """Inicializa o banco de dados com a tabela necessária"""
    try:
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS mensagens (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            remetente TEXT,
            categoria TEXT NOT NULL,
            contexto TEXT NOT NULL,
            mudanca_chave TEXT NOT NULL,
            mensagem_original TEXT NOT NULL,
            projeto TEXT,
            lesson_learned TEXT NOT NULL DEFAULT 'não',
            mensagem_hash TEXT UNIQUE
        )
        ''')
        
        conn.commit()
        conn.close()
        print(f"Banco de dados '{DB_NAME}' inicializado com sucesso!")
    except Exception as e:
        print(f"Erro ao inicializar banco: {e}")

def gerar_hash_mensagem(projeto_id, categoria, mensagem):
    """Gera um hash único para a mensagem para evitar duplicatas"""
    conteudo = f"{projeto_id}_{categoria}_{mensagem}".lower().strip()
    return hashlib.md5(conteudo.encode()).hexdigest()

def verificar_duplicata(projeto_id, categoria, mensagem):
    """Verifica se já existe uma mensagem idêntica no banco de dados"""
    try:
        mensagem_hash = gerar_hash_mensagem(projeto_id, categoria, mensagem)
        
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        
        cursor.execute('''
        SELECT COUNT(*) FROM mensagens WHERE mensagem_hash = ?
        ''', (mensagem_hash,))
        
        count = cursor.fetchone()[0]
        conn.close()
        
        return count > 0
    except Exception as e:
        print(f"Erro ao verificar duplicata: {e}")
        return False

def processar_contexto_mensagem(mensagem):
    """
    Usa o DeepSeek APENAS para extrair o contexto e mudança chave da mensagem,
    já que categoria e projeto já foram fornecidos pelo usuário
    """
    headers = {
        "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
        "Content-Type": "application/json"
    }
    
    prompt = f"""
    Analise a seguinte mensagem relacionada a projetos de construção e extraia APENAS:
    
    1. Um breve contexto da informação
    2. A mudança chave ou registro importante mencionado
    
    MENSAGEM: "{mensagem}"
    
    Retorne APENAS um JSON com a seguinte estrutura:
    {{
        "contexto": "breve descrição do contexto",
        "mudanca_chave": "descrição clara da mudança ou registro"
    }}
    """
    
    payload = {
        "model": "deepseek-chat",
        "messages": [
            {
                "role": "system", 
                "content": "Você é um assistente especializado em análise de mensagens de projetos de construção civil. Extraia informações de contexto de forma preciso."
            },
            {
                "role": "user", 
                "content": prompt
            }
        ],
        "temperature": 0.1,
        "max_tokens": 500
    }
    
    try:
        response = requests.post(DEEPSEEK_API_URL, headers=headers, json=payload, timeout=30)
        response.raise_for_status()
        response_data = response.json()
        
        conteudo = response_data['choices'][0]['message']['content']
        
        # Extrair JSON da resposta
        json_match = re.search(r'\{.*\}', conteudo, re.DOTALL)
        if json_match:
            json_str = json_match.group()
            dados = json.loads(json_str)
            return dados
        else:
            print("Erro: JSON não encontrado na resposta da API")
            return {
                "contexto": "Informação registrada via formulário",
                "mudanca_chave": mensagem[:100] + "..." if len(mensagem) > 100 else mensagem
            }
            
    except Exception as e:
        print(f"Erro ao processar contexto: {e}")
        return {
            "contexto": "Informação registrada via formulário",
            "mudanca_chave": mensagem[:100] + "..." if len(mensagem) > 100 else mensagem
        }

def salvar_no_banco(projeto_id, categoria, data_info, mensagem, lesson_learned):
    """
    Salva os dados processados no banco de dados
    Usa as informações do formulário diretamente para projeto e categoria
    """
    # Verificar duplicata antes de processar
    if verificar_duplicata(projeto_id, categoria, mensagem):
        return False, "Esta informação já foi registrada anteriormente."
    
    # Processar apenas o contexto e mudança chave com DeepSeek
    dados_processados = processar_contexto_mensagem(mensagem)
    
    # Gerar hash único para a mensagem
    mensagem_hash = gerar_hash_mensagem(projeto_id, categoria, mensagem)
    
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    
    try:
        cursor.execute('''
        INSERT INTO mensagens (timestamp, remetente, categoria, contexto, mudanca_chave, mensagem_original, projeto, lesson_learned, mensagem_hash)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            data_info,
            None,  # Remetente não é coletado no formulário
            categoria,  # Usa a categoria fornecida pelo usuário
            dados_processados.get('contexto', ''),
            dados_processados.get('mudanca_chave', ''),
            mensagem,
            projeto_id,  # Usa o projeto ID fornecido pelo usuário
            lesson_learned,  # 'sim' ou 'não'
            mensagem_hash
        ))
        
        conn.commit()
        conn.close()
        print("Mensagem salva no banco de dados com sucesso!")
        return True, "Informação registrada com sucesso!"
        
    except sqlite3.IntegrityError:
        conn.close()
        print("Tentativa de inserir mensagem duplicada")
        return False, "Esta informação já foi registrada anteriormente."
    except Exception as e:
        conn.close()
        print(f"Erro ao salvar no banco: {e}")
        return False, f"Erro ao processar a mensagem: {str(e)}"

# Carregar projetos uma vez ao iniciar o aplicativo
PROJETOS = carregar_projetos()

# Inicializar o analisador de banco de dados
db_analyzer = DBAnalyzer(DEEPSEEK_API_KEY, DB_NAME)

# Rota para servir arquivos estáticos
@app.route('/static/<path:filename>')
def serve_static(filename):
    try:
        return send_from_directory(app.static_folder, filename)
    except Exception as e:
        print(f"Erro ao servir arquivo estático {filename}: {e}")
        return "Arquivo não encontrado", 404

# ... (código anterior permanece igual)

# ========== ROTAS PRINCIPAIS ==========

@app.route('/')
def index():
    return HTML_BASE

@app.route('/consulta')
def consulta():
    return HTML_BASE

# ========== API ROUTES ==========

@app.route('/api/projetos')
def api_projetos():
    """API para retornar a lista de projetos"""
    try:
        return jsonify({
            'success': True, 
            'projetos': PROJETOS
        })
    except Exception as e:
        return jsonify({
            'success': False, 
            'message': f'Erro ao carregar projetos: {str(e)}'
        })

@app.route('/api/selecionar_projeto', methods=['POST'])
def selecionar_projeto():
    """API para selecionar um projeto na sessão"""
    try:
        data = request.get_json()
        projeto_id = data.get('projeto_id')
        
        if not projeto_id:
            session.pop('projeto_selecionado', None)
            return jsonify({'success': True, 'projeto_nome': None})
        
        # Encontrar o projeto na lista
        projeto = next((p for p in PROJETOS if p['id'] == projeto_id), None)
        
        if projeto:
            session['projeto_selecionado'] = {
                'id': projeto['id'],
                'nome': projeto['display']
            }
            return jsonify({'success': True, 'projeto_nome': projeto['display']})
        else:
            return jsonify({'success': False, 'message': 'Projeto não encontrado'})
            
    except Exception as e:
        return jsonify({'success': False, 'message': f'Erro: {str(e)}'})

@app.route('/api/conteudo/<pagina>')
def api_conteudo(pagina):
    """API para retornar o conteúdo das páginas"""
    try:
        projeto = session.get('projeto_selecionado')
        
        if pagina == 'entrada':
            titulo = "Entrada de Informação"
            subtitulo = projeto['nome'] if projeto else "Selecione um projeto no menu para começar"
            conteudo = HTML_ENTRADA
        elif pagina == 'consulta':
            titulo = "Consulta de Informações"
            subtitulo = projeto['nome'] if projeto else "Chatbot para consultar e analisar dados"
            conteudo = HTML_CONSULTA
        else:
            return jsonify({'success': False, 'message': 'Página não encontrada'})
            
        return jsonify({
            'success': True,
            'titulo': titulo,
            'subtitulo': subtitulo,
            'conteudo': conteudo
        })
            
    except Exception as e:
        return jsonify({'success': False, 'message': f'Erro: {str(e)}'})

@app.route('/api/verificar_duplicata', methods=['POST'])
def api_verificar_duplicata():
    """API para verificar se uma mensagem é duplicada"""
    try:
        data = request.get_json()
        projeto_id = data.get('projeto_id')
        categoria = data.get('categoria')
        mensagem = data.get('mensagem')
        
        if not all([projeto_id, categoria, mensagem]):
            return jsonify({'success': False, 'is_duplicata': False})
        
        is_duplicata = verificar_duplicata(projeto_id, categoria, mensagem)
        return jsonify({'success': True, 'is_duplicata': is_duplicata})
        
    except Exception as e:
        return jsonify({'success': False, 'is_duplicata': False})

@app.route('/api/registrar_mensagem', methods=['POST'])
def registrar_mensagem():
    try:
        data = request.get_json()
        projeto_id = data.get('projeto_id')
        categoria = data.get('categoria')
        data_info = data.get('data_info')
        mensagem = data.get('mensagem')
        lesson_learned = data.get('lesson_learned', 'não')
        
        if not all([projeto_id, categoria, data_info, mensagem, lesson_learned]):
            return jsonify({'success': False, 'message': 'Todos os campos são obrigatórios'})
        
        # Salvar no banco de dados
        success, message = salvar_no_banco(projeto_id, categoria, data_info, mensagem, lesson_learned)
        
        return jsonify({'success': success, 'message': message})
            
    except Exception as e:
        return jsonify({'success': False, 'message': f'Erro: {str(e)}'})

@app.route('/api/consultar_dados', methods=['POST'])
def consultar_dados():
    try:
        data = request.get_json()
        question = data.get('question')
        projeto_id = data.get('projeto_id')
        
        if not question:
            return jsonify({'success': False, 'message': 'Pergunta não fornecida'})
        
        # Usar o DBAnalyzer para processar a pergunta com filtro de projeto
        answer = db_analyzer.ask_question(question, projeto_id)
        
        return jsonify({'success': True, 'answer': answer})
        
    except Exception as e:
        return jsonify({'success': False, 'message': f'Erro: {str(e)}'})

@app.route('/api/ultimas_mensagens')
def ultimas_mensagens():
    try:
        limite = request.args.get('limite', 10)
        projeto_id = session.get('projeto_selecionado', {}).get('id')
        
        where_clause = f" WHERE projeto = '{projeto_id}'" if projeto_id else ""
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        query = f"SELECT * FROM mensagens{where_clause} ORDER BY timestamp DESC LIMIT {limite}"
        cursor.execute(query)
        
        # Converter para lista de dicionários
        columns = [description[0] for description in cursor.description]
        mensagens = []
        for row in cursor.fetchall():
            mensagens.append(dict(zip(columns, row)))
            
        conn.close()
        return jsonify({'success': True, 'mensagens': mensagens})
    except Exception as e:
        return jsonify({'success': False, 'message': f'Erro: {str(e)}'})

# ========== ROTA DE HEALTH CHECK ==========

@app.route('/health')
def health_check():
    return jsonify({'status': 'ok', 'message': 'Sistema funcionando'})

# ========== INICIALIZAÇÃO ==========

if __name__ == '__main__':
    # Inicializar o banco de dados
    inicializar_banco()
    
    # No Render, use a porta fornecida pela variável de ambiente
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)

# ... (TODO O RESTO DO CÓDIGO DAS ROTAS API PERMANECE IGUAL)

if __name__ == '__main__':
    # Inicializar o banco de dados
    inicializar_banco()
    
    # No Render, use a porta fornecida pela variável de ambiente
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)

