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
        
        # Verificar se está vazio e adicionar dados de exemplo
        cursor.execute("SELECT COUNT(*) FROM mensagens")
        count = cursor.fetchone()[0]
        
        if count == 0:
            print("Banco vazio. Adicionando dados de exemplo...")
            # Adicionar alguns dados de exemplo
            exemplos = [
                ('2024-01-01 10:00:00', None, 'Informações base', 
                 'Configuração inicial', 'Sistema implantado', 
                 'Sistema de registro de projetos foi implantado com sucesso',
                 '10001', 'não', 'hash_exemplo_1'),
                 
                ('2024-01-02 14:30:00', None, 'Lessons learned - Materiais',
                 'Problema com fornecedor', 'Mudar fornecedor de concreto',
                 'Fornecedor XYZ atrasou entrega em 15 dias, recomendo mudar para ABC',
                 '10001', 'sim', 'hash_exemplo_2')
            ]
            
            for exemplo in exemplos:
                try:
                    cursor.execute('''
                    INSERT INTO mensagens (timestamp, remetente, categoria, contexto, 
                                         mudanca_chave, mensagem_original, projeto, lesson_learned, mensagem_hash)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ''', exemplo)
                except sqlite3.IntegrityError:
                    continue  # Pula se já existir
        
        conn.commit()
        conn.close()
        print(f"Banco de dados '{DB_NAME}' inicializado com sucesso! ({count} registros existentes)")
        
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

# ========== HTML CONTENT ==========

HTML_BASE = '''
<!DOCTYPE html>
<html lang="pt-BR">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Sistema de Registro de Projetos</title>
    <style>
        body {
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            margin: 0;
            padding: 0;
            background-color: #f5f5f5;
            color: #333;
            display: flex;
        }
        .sidebar {
            width: 250px;
            background-color: #2c3e50;
            color: white;
            height: 100vh;
            padding: 20px;
            position: fixed;
            display: flex;
            flex-direction: column;
        }
        .sidebar-content {
            flex: 1;
        }
        .sidebar h2 {
            text-align: center;
            margin-bottom: 30px;
        }
        .sidebar nav ul {
            list-style: none;
            padding: 0;
            margin-bottom: 30px;
        }
        .sidebar nav ul li {
            margin-bottom: 10px;
        }
        .sidebar nav ul li a {
            color: white;
            text-decoration: none;
            padding: 10px 15px;
            display: block;
            border-radius: 4px;
            transition: background-color 0.3s;
        }
        .sidebar nav ul li a:hover {
            background-color: #34495e;
        }
        .sidebar nav ul li a.active {
            background-color: #3498db;
        }
        .projeto-selecionado {
            background-color: #27ae60;
            padding: 10px;
            border-radius: 4px;
            margin-bottom: 20px;
            text-align: center;
        }
        .projeto-nao-selecionado {
            background-color: #e74c3c;
            padding: 10px;
            border-radius: 4px;
            margin-bottom: 20px;
            text-align: center;
        }
        .select-projeto {
            width: 100%;
            padding: 8px;
            margin-bottom: 15px;
            border-radius: 4px;
            border: none;
        }
        .sidebar-image {
            margin-top: auto;
            text-align: center;
            padding: 10px 0;
            border-top: 1px solid #34495e;
        }
        .sidebar-image img {
            max-width: 100%;
            height: auto;
            border-radius: 5px;
        }
        .main-content {
            margin-left: 250px;
            padding: 20px;
            width: calc(100% - 250px);
        }
        .container {
            max-width: 800px;
            margin: 0 auto;
        }
        header {
            background-color: #2c3e50;
            color: white;
            padding: 20px;
            text-align: center;
            border-radius: 5px 5px 0 0;
        }
        .chat-container {
            background-color: white;
            border-radius: 0 0 5px 5px;
            box-shadow: 0 2px 10px rgba(0, 0, 0, 0.1);
            padding: 20px;
            margin-bottom: 20px;
        }
        .message {
            margin-bottom: 15px;
            padding: 10px;
            border-radius: 5px;
        }
        .bot-message {
            background-color: #e8f4f8;
            border-left: 4px solid #3498db;
        }
        .user-message {
            background-color: #f0f7f0;
            border-left: 4px solid #2ecc71;
            text-align: right;
        }
        .input-group {
            margin-bottom: 15px;
        }
        label {
            display: block;
            margin-bottom: 5px;
            font-weight: bold;
        }
        input, select, textarea {
            width: 100%;
            padding: 10px;
            border: 1px solid #ddd;
            border-radius: 4px;
            box-sizing: border-box;
        }
        button {
            background-color: #3498db;
            color: white;
            border: none;
            padding: 10px 15px;
            border-radius: 4px;
            cursor: pointer;
            font-size: 16px;
            margin-top: 10px;
        }
        button:hover {
            background-color: #2980b9;
        }
        button:disabled {
            background-color: #95a5a6;
            cursor: not-allowed;
        }
        .hidden {
            display: none;
        }
        .option-buttons {
            display: flex;
            flex-wrap: wrap;
            gap: 10px;
            margin-bottom: 15px;
        }
        .option-button {
            padding: 10px 15px;
            background-color: #ecf0f1;
            border: 1px solid #bdc3c7;
            border-radius: 4px;
            cursor: pointer;
            text-align: center;
            min-width: 100px;
        }
        .option-button.selected {
            background-color: #3498db;
            color: white;
            border-color: #2980b9;
        }
        #chat-messages {
            max-height: 300px;
            overflow-y: auto;
            margin-bottom: 20px;
        }
        .success-message {
            color: #27ae60;
            font-weight: bold;
        }
        .error-message {
            color: #e74c3c;
            font-weight: bold;
        }
        .no-projeto-selecionado {
            text-align: center;
            padding: 40px;
            background-color: #f8f9fa;
            border-radius: 5px;
            color: #6c757d;
        }
    </style>
</head>
<body>
    <div class="sidebar">
        <div class="sidebar-content">
            <h2>Menu</h2>
            
            <div id="projeto-info">
                <select id="projeto-select" class="select-projeto">
                    <option value="">-- Selecione um Projeto --</option>
                </select>
                <button onclick="selecionarProjeto()" style="width: 100%; margin-top: 0;">Selecionar Projeto</button>
                <div id="projeto-status" class="projeto-nao-selecionado">
                    Nenhum projeto selecionado
                </div>
            </div>
            
            <nav>
                <ul>
                    <li><a href="#" onclick="carregarPagina('entrada')" id="nav-entrada" class="active">Entrada de Informação</a></li>
                    <li><a href="#" onclick="carregarPagina('consulta')" id="nav-consulta">Consulta de Informação</a></li>
                </ul>
            </nav>
        </div>
        
        <div class="sidebar-image">
            <img src="/static/PPP.png" alt="Logo">
        </div>
    </div>

    <div class="main-content">
        <div class="container">
            <header>
                <h1 id="titulo-pagina">Sistema de Registro de Projetos</h1>
                <p id="subtitulo-pagina">Selecione um projeto no menu para começar</p>
            </header>

            <div id="conteudo-pagina">
                <div class="no-projeto-selecionado">
                    <h3>Selecione um projeto no menu lateral para começar</h3>
                    <p>Escolha um projeto na lista dropdown e clique em "Selecionar Projeto"</p>
                </div>
            </div>
        </div>
    </div>

    <script>
        let projetoSelecionado = null;
        let paginaAtual = 'entrada';
        
        window.onload = function() {
            carregarListaProjetos();
        };
        
        function carregarListaProjetos() {
            fetch('/api/projetos')
                .then(response => response.json())
                .then(data => {
                    if (data.success) {
                        const select = document.getElementById('projeto-select');
                        while (select.options.length > 1) {
                            select.remove(1);
                        }
                        
                        data.projetos.forEach(projeto => {
                            const option = document.createElement('option');
                            option.value = projeto.id;
                            option.textContent = projeto.display;
                            select.appendChild(option);
                        });
                    }
                })
                .catch(error => {
                    console.error('Erro ao carregar projetos:', error);
                });
        }
        
        function selecionarProjeto() {
            const select = document.getElementById('projeto-select');
            const projetoId = select.value;
            
            if (!projetoId) {
                alert("Por favor, selecione um projeto da lista.");
                return;
            }
            
            fetch('/api/selecionar_projeto', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({ projeto_id: projetoId })
            })
            .then(response => response.json())
            .then(data => {
                if (data.success) {
                    projetoSelecionado = {
                        id: projetoId,
                        nome: data.projeto_nome
                    };
                    atualizarStatusProjeto();
                    carregarPagina(paginaAtual);
                } else {
                    alert('Erro ao selecionar projeto: ' + data.message);
                }
            })
            .catch(error => {
                console.error('Erro:', error);
                alert('Erro ao selecionar projeto');
            });
        }
        
        function atualizarStatusProjeto() {
            const statusDiv = document.getElementById('projeto-status');
            const select = document.getElementById('projeto-select');
            
            if (projetoSelecionado) {
                statusDiv.className = 'projeto-selecionado';
                statusDiv.innerHTML = `Projeto: <strong>${projetoSelecionado.nome}</strong>`;
                select.value = projetoSelecionado.id;
            } else {
                statusDiv.className = 'projeto-nao-selecionado';
                statusDiv.textContent = 'Nenhum projeto selecionado';
                select.value = '';
            }
        }
        
        function carregarPagina(pagina) {
            paginaAtual = pagina;
            
            document.querySelectorAll('.sidebar nav a').forEach(link => {
                link.classList.remove('active');
            });
            document.getElementById(`nav-${pagina}`).classList.add('active');
            
            fetch(`/api/conteudo/${pagina}`)
                .then(response => response.json())
                .then(data => {
                    if (data.success) {
                        document.getElementById('conteudo-pagina').innerHTML = data.conteudo;
                        document.getElementById('titulo-pagina').textContent = data.titulo;
                        document.getElementById('subtitulo-pagina').textContent = data.subtitulo;
                        
                        if (pagina === 'entrada') {
                            inicializarEntrada();
                        } else if (pagina === 'consulta') {
                            inicializarConsulta();
                        }
                    }
                })
                .catch(error => {
                    console.error('Erro ao carregar conteúdo:', error);
                    document.getElementById('conteudo-pagina').innerHTML = '<div class="error-message">Erro ao carregar a página</div>';
                });
        }
        
        function inicializarEntrada() {
            console.log('Entrada inicializada');
        }
        
        function inicializarConsulta() {
            console.log('Consulta inicializada');
        }
    </script>
</body>
</html>
'''

HTML_ENTRADA = '''
<div class="chat-container">
    <div id="chat-messages">
        <div class="message bot-message" id="mensagem-inicial">
            Carregando...
        </div>
    </div>

    <div id="input-section">
        <div id="categoria-step" class="input-group hidden">
            <label>Selecione a categoria:</label>
            <div class="option-buttons">
                <div class="option-button" onclick="selectCategory(this, 'Informações base')">Informações base</div>
                <div class="option-button" onclick="selectCategory(this, 'Envoltória')">Envoltória</div>
                <div class="option-button" onclick="selectCategory(this, 'Materiais')">Materiais</div>
                <div class="option-button" onclick="selectCategory(this, 'Água')">Água</div>
                <div class="option-button" onclick="selectCategory(this, 'HVAC')">HVAC</div>
                <div class="option-button" onclick="selectCategory(this, 'Elétrica')">Elétrica</div>
                <div class="option-button" onclick="selectCategory(this, 'LEED')">LEED</div>
                <div class="option-button" onclick="selectCategory(this, 'Lessons learned')">Lessons learned</div>
                <div class="option-button" onclick="selectCategory(this, 'Outros')">Outros</div>
            </div>
            <button onclick="submitCategory()">Enviar</button>
        </div>

        <div id="subcategoria-step" class="input-group hidden">
            <label>Selecione a subcategoria da Lesson Learned:</label>
            <div class="option-buttons">
                <div class="option-button" onclick="selectSubCategory(this, 'Informações base')">Informações base</div>
                <div class="option-button" onclick="selectSubCategory(this, 'Envoltória')">Envoltória</div>
                <div class="option-button" onclick="selectSubCategory(this, 'Materiais')">Materiais</div>
                <div class="option-button" onclick="selectSubCategory(this, 'Água')">Água</div>
                <div class="option-button" onclick="selectSubCategory(this, 'HVAC')">HVAC</div>
                <div class="option-button" onclick="selectSubCategory(this, 'Elétrica')">Elétrica</div>
                <div class="option-button" onclick="selectSubCategory(this, 'LEED')">LEED</div>
                <div class="option-button" onclick="selectSubCategory(this, 'Outros')">Outros</div>
            </div>
            <button onclick="submitSubCategory()">Enviar</button>
        </div>

        <div id="data-step" class="input-group hidden">
            <label for="data-info">Data da Informação:</label>
            <input type="datetime-local" id="data-info">
            <button onclick="submitDate()">Enviar</button>
        </div>

        <div id="mensagem-step" class="input-group hidden">
            <label for="mensagem">Informação:</label>
            <textarea id="mensagem" rows="4" placeholder="Digite a informação que deseja registrar"></textarea>
            <button onclick="submitMessage()">Registrar Informação</button>
        </div>
    </div>
</div>

<script>
    function inicializarEntrada() {
        const now = new Date();
        const localDateTime = now.toISOString().slice(0, 16);
        document.getElementById('data-info').value = localDateTime;
        
        const mensagemInicial = document.getElementById('mensagem-inicial');
        if (projetoSelecionado) {
            mensagemInicial.textContent = 
                `Olá! Você está registrando informações para o projeto ${projetoSelecionado.nome}. Selecione a categoria da informação.`;
            document.getElementById('categoria-step').classList.remove('hidden');
        } else {
            mensagemInicial.textContent = 
                'Por favor, selecione um projeto no menu lateral para começar a registrar informações.';
        }
    }
    
    window.selectCategory = function(element, selectedCategory) {
        if (!projetoSelecionado) return;
        
        const buttons = document.querySelectorAll('#categoria-step .option-button');
        buttons.forEach(button => button.classList.remove('selected'));
        
        element.classList.add('selected');
        window.currentCategory = selectedCategory;
        window.isLessonLearned = (selectedCategory === 'Lessons learned');
    };
    
    window.submitCategory = function() {
        if (!projetoSelecionado) {
            alert("Por favor, selecione um projeto primeiro.");
            return;
        }
        
        if (!window.currentCategory) {
            alert("Por favor, selecione uma categoria.");
            return;
        }
        
        addMessage(`Categoria: ${window.currentCategory}`, "user");
        document.getElementById('categoria-step').classList.add('hidden');
        
        if (window.isLessonLearned) {
            document.getElementById('subcategoria-step').classList.remove('hidden');
            addMessage("Agora selecione a subcategoria desta Lesson Learned.", "bot");
        } else {
            document.getElementById('data-step').classList.remove('hidden');
            addMessage("Agora informe a data da informação.", "bot");
        }
    };
    
    window.selectSubCategory = function(element, selectedSubCategory) {
        const buttons = document.querySelectorAll('#subcategoria-step .option-button');
        buttons.forEach(button => button.classList.remove('selected'));
        
        element.classList.add('selected');
        window.currentSubCategory = selectedSubCategory;
    };
    
    window.submitSubCategory = function() {
        if (!window.currentSubCategory) {
            alert("Por favor, selecione uma subcategoria.");
            return;
        }
        
        addMessage(`Subcategoria: ${window.currentSubCategory}`, "user");
        document.getElementById('subcategoria-step').classList.add('hidden');
        document.getElementById('data-step').classList.remove('hidden');
        addMessage("Agora informe a data da informação.", "bot");
    };
    
    window.submitDate = function() {
        const dataInfo = document.getElementById('data-info').value;
        if (!dataInfo) {
            alert("Por favor, informe a data.");
            return;
        }
        
        addMessage(`Data: ${new Date(dataInfo).toLocaleString('pt-BR')}`, "user");
        document.getElementById('data-step').classList.add('hidden');
        document.getElementById('mensagem-step').classList.remove('hidden');
        addMessage("Por fim, digite a informação que deseja registrar.", "bot");
    };
    
    window.submitMessage = function() {
        const mensagem = document.getElementById('mensagem').value.trim();
        if (!mensagem) {
            alert("Por favor, digite a informação.");
            return;
        }
        
        addMessage(`Informação: ${mensagem}`, "user");
        addMessage("Processando e salvando a informação...", "bot");
        
        let categoriaFinal = window.currentCategory;
        if (window.isLessonLearned) {
            categoriaFinal = `Lessons learned - ${window.currentSubCategory}`;
        }
        
        const lessonLearned = window.isLessonLearned ? 'sim' : 'não';
        
        fetch('/api/registrar_mensagem', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                projeto_id: projetoSelecionado.id,
                categoria: categoriaFinal,
                data_info: document.getElementById('data-info').value,
                mensagem: mensagem,
                lesson_learned: lessonLearned
            })
        })
        .then(response => response.json())
        .then(data => {
            const chatMessages = document.getElementById('chat-messages');
            if (chatMessages.lastChild.textContent.includes("Processando")) {
                chatMessages.removeChild(chatMessages.lastChild);
            }
            
            if (data.success) {
                const successMsg = window.isLessonLearned 
                    ? "✅ Lesson Learned registrada com sucesso!" 
                    : "✅ Informação registrada com sucesso!";
                
                addMessage(successMsg, "bot");
                
                // Resetar formulário
                document.getElementById('mensagem').value = '';
                document.querySelectorAll('.option-button').forEach(btn => btn.classList.remove('selected'));
                document.getElementById('categoria-step').classList.remove('hidden');
                document.getElementById('subcategoria-step').classList.add('hidden');
                document.getElementById('data-step').classList.add('hidden');
                document.getElementById('mensagem-step').classList.add('hidden');
                
                window.currentCategory = '';
                window.currentSubCategory = '';
                window.isLessonLearned = false;
                
                addMessage("Selecione a categoria para registrar nova informação.", "bot");
            } else {
                addMessage(`❌ Erro: ${data.message}`, "bot");
            }
        })
        .catch(error => {
            addMessage(`❌ Erro ao conectar com o servidor: ${error}`, "bot");
        });
    };
    
    function addMessage(text, sender) {
        const messageDiv = document.createElement('div');
        messageDiv.classList.add('message');
        messageDiv.classList.add(sender === 'bot' ? 'bot-message' : 'user-message');
        messageDiv.textContent = text;
        
        document.getElementById('chat-messages').appendChild(messageDiv);
        document.getElementById('chat-messages').scrollTop = document.getElementById('chat-messages').scrollHeight;
    }
</script>
'''

HTML_CONSULTA = '''
<div class="chat-container">
    <div id="chat-messages">
        <div class="message bot-message">
            Carregando...
        </div>
    </div>

    <div class="input-group">
        <input type="text" id="user-question" placeholder="Digite sua pergunta sobre os dados..." style="width: 100%; padding: 10px; margin-bottom: 10px;">
        <button onclick="askQuestion()" style="width: 100%;">Enviar Pergunta</button>
    </div>
</div>

<script>
    function inicializarConsulta() {
        const mensagemInicial = document.querySelector('#chat-messages .bot-message');
        if (projetoSelecionado) {
            mensagemInicial.textContent = 
                `Olá! Sou seu assistente para consulta de informações do projeto ${projetoSelecionado.nome}. ` +
                `Posso ajudar você a analisar os dados deste projeto. O que gostaria de saber?`;
        } else {
            mensagemInicial.textContent = 
                'Olá! Sou seu assistente para consulta de informações do banco de dados. ' +
                'Selecione um projeto no menu lateral para consultar dados específicos.';
        }
    }
    
    window.askQuestion = function() {
        const question = document.getElementById('user-question').value.trim();
        if (!question) {
            alert('Por favor, digite uma pergunta.');
            return;
        }

        addMessage(question, 'user');
        document.getElementById('user-question').value = '';

        const loadingId = addMessage('Analisando sua pergunta...', 'bot', true);

        const projetoId = projetoSelecionado ? projetoSelecionado.id : null;

        fetch('/api/consultar_dados', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({ 
                question: question,
                projeto_id: projetoId
            })
        })
        .then(response => response.json())
        .then(data => {
            removeLoadingMessage(loadingId);

            if (data.success) {
                addMessage(data.answer, 'bot');
            } else {
                addMessage('❌ Erro: ' + data.message, 'bot');
            }
        })
        .catch(error => {
            removeLoadingMessage(loadingId);
            addMessage('❌ Erro ao conectar com o servidor: ' + error, 'bot');
        });
    };

    function addMessage(text, sender, isTemp = false) {
        const chatMessages = document.getElementById('chat-messages');
        const messageDiv = document.createElement('div');
        messageDiv.classList.add('message');
        messageDiv.classList.add(sender === 'bot' ? 'bot-message' : 'user-message');
        
        if (isTemp) {
            messageDiv.classList.add('loading');
            messageDiv.id = 'temp-' + Date.now();
        }
        
        messageDiv.textContent = text;
        chatMessages.appendChild(messageDiv);
        chatMessages.scrollTop = chatMessages.scrollHeight;
        
        return isTemp ? messageDiv.id : null;
    }

    function removeLoadingMessage(id) {
        const element = document.getElementById(id);
        if (element) {
            element.remove();
        }
    }
</script>
'''

# ========== ROTAS ==========

@app.route('/')
def index():
    return HTML_BASE

@app.route('/consulta')
def consulta():
    return HTML_BASE

@app.route('/health')
def health_check():
    return jsonify({'status': 'ok', 'message': 'Sistema funcionando'})

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

# Rota para servir arquivos estáticos
@app.route('/static/<path:filename>')
def serve_static(filename):
    try:
        return send_from_directory(app.static_folder, filename)
    except Exception as e:
        print(f"Erro ao servir arquivo estático {filename}: {e}")
        return "Arquivo não encontrado", 404

if __name__ == '__main__':
    # Inicializar o banco de dados
    inicializar_banco()
    
    # No Render, use a porta fornecida pela variável de ambiente
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
