from flask import Flask, request, jsonify, session, send_file
import json
import re
from datetime import datetime
import os
import hashlib
import requests
import csv
import io
import dropbox
from dropbox.exceptions import AuthError, ApiError

# Configurações do Dropbox - usar variáveis de ambiente
DROPBOX_ACCESS_TOKEN = os.getenv("DROPBOX_ACCESS_TOKEN", "seu_token_dropbox_aqui")
DROPBOX_DB_PATH = "/mensagens_projetos.json"

# Configuração da API DeepSeek
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "sk-3133a53daa7b44ccabd6805286671f6b")
DEEPSEEK_API_URL = "https://api.deepseek.com/v1/chat/completions"

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "sua_chave_secreta_aqui_producao_12345")

# Configurar para produção
app.config['SESSION_COOKIE_SECURE'] = os.getenv('FLASK_ENV') == 'production'
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'

# Estrutura padrão do banco de dados no Dropbox
DB_STRUCTURE = {
    "mensagens": [],
    "estatisticas": {
        "total_mensagens": 0,
        "ultima_atualizacao": None
    }
}

def carregar_projetos_csv():
    """Carrega a lista de projetos do arquivo CSV sem usar pandas"""
    try:
        # Verificar se o arquivo existe
        if not os.path.exists('projetos.csv'):
            print("Arquivo projetos.csv não encontrado. Criando arquivo de exemplo...")
            # Criar um arquivo de exemplo
            with open('projetos.csv', 'w', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                writer.writerow(['ID', 'Projeto'])
                writer.writerow([1, 'Projeto A'])
                writer.writerow([2, 'Projeto B'])
                writer.writerow([3, 'Projeto C'])
            print("Arquivo projetos.csv de exemplo criado.")
        
        projetos = []
        with open('projetos.csv', 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                projetos.append({
                    'id': str(row['ID']),
                    'nome': row['Projeto'],
                    'display': f"{row['ID']} - {row['Projeto']}"
                })
        
        print(f"✅ Projetos carregados do CSV: {len(projetos)}")
        return projetos
        
    except Exception as e:
        print(f"❌ Erro ao carregar projetos do CSV: {e}")
        # Retorna projetos padrão se houver erro
        return [
            {'id': '1', 'nome': 'Projeto A', 'display': '1 - Projeto A'},
            {'id': '2', 'nome': 'Projeto B', 'display': '2 - Projeto B'},
            {'id': '3', 'nome': 'Projeto C', 'display': '3 - Projeto C'}
        ]

def carregar_banco_dropbox():
    """Carrega o banco de dados do Dropbox"""
    try:
        dbx = dropbox.Dropbox(DROPBOX_ACCESS_TOKEN)
        
        # Tenta baixar o arquivo
        metadata, response = dbx.files_download(DROPBOX_DB_PATH)
        
        # Carrega o JSON
        dados = json.loads(response.content.decode('utf-8'))
        print("✅ Banco de dados carregado do Dropbox com sucesso!")
        return dados
        
    except dropbox.exceptions.HttpError as e:
        if e.status == 409:  # Arquivo não encontrado
            print("📁 Arquivo não encontrado no Dropbox. Criando novo banco de dados...")
            # Salva a estrutura inicial
            salvar_banco_dropbox(DB_STRUCTURE)
            return DB_STRUCTURE
        else:
            print(f"❌ Erro HTTP ao carregar do Dropbox: {e}")
            return DB_STRUCTURE
    except Exception as e:
        print(f"❌ Erro ao carregar do Dropbox: {e}")
        return DB_STRUCTURE

def salvar_banco_dropbox(dados):
    """Salva o banco de dados no Dropbox"""
    try:
        dbx = dropbox.Dropbox(DROPBOX_ACCESS_TOKEN)
        
        # Converte para JSON
        json_data = json.dumps(dados, ensure_ascii=False, indent=2)
        
        # Faz upload do arquivo
        dbx.files_upload(
            json_data.encode('utf-8'), 
            DROPBOX_DB_PATH, 
            mode=dropbox.files.WriteMode.overwrite
        )
        
        print("✅ Banco de dados salvo no Dropbox com sucesso!")
        return True
        
    except Exception as e:
        print(f"❌ Erro ao salvar no Dropbox: {e}")
        return False

def upload_db_to_dropbox():
    """Faz upload do banco de dados para o Dropbox (para backup)"""
    try:
        # Simplesmente salva o banco atual
        banco = carregar_banco_dropbox()
        success = salvar_banco_dropbox(banco)
        if success:
            return True, "Backup salvo no Dropbox com sucesso!"
        else:
            return False, "Erro ao fazer backup"
        
    except Exception as e:
        return False, f"Erro ao fazer upload: {e}"

def download_db_from_dropbox():
    """Baixa o banco de dados do Dropbox (para restore)"""
    try:
        # Simplesmente carrega o banco - já está sincronizado
        banco = carregar_banco_dropbox()
        return True, "Backup restaurado do Dropbox com sucesso!"
        
    except Exception as e:
        return False, f"Erro ao baixar: {e}"

def gerar_hash_mensagem(projeto_id, categoria, mensagem):
    """Gera um hash único para a mensagem para evitar duplicatas"""
    conteudo = f"{projeto_id}_{categoria}_{mensagem}".lower().strip()
    return hashlib.md5(conteudo.encode()).hexdigest()

def verificar_duplicata(projeto_id, categoria, mensagem):
    """Verifica se já existe uma mensagem idêntica no banco de dados"""
    try:
        banco = carregar_banco_dropbox()
        mensagens = banco.get("mensagens", [])
        
        mensagem_hash = gerar_hash_mensagem(projeto_id, categoria, mensagem)
        
        for msg in mensagens:
            if msg.get("mensagem_hash") == mensagem_hash:
                return True
        
        return False
    except Exception as e:
        print(f"Erro ao verificar duplicata: {e}")
        return False

def processar_contexto_mensagem(mensagem):
    """
    Usa o DeepSeek APENAS para extrair o contexto e mudança chave da mensagem
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

def salvar_mensagem(projeto_id, categoria, data_info, mensagem, lesson_learned):
    """
    Salva os dados processados no Dropbox
    """
    # Verificar duplicata antes de processar
    if verificar_duplicata(projeto_id, categoria, mensagem):
        return False, "Esta informação já foi registrada anteriormente."
    
    # Processar apenas o contexto e mudança chave com DeepSeek
    dados_processados = processar_contexto_mensagem(mensagem)
    
    # Gerar hash único para a mensagem
    mensagem_hash = gerar_hash_mensagem(projeto_id, categoria, mensagem)
    
    try:
        # Carrega o banco atual
        banco = carregar_banco_dropbox()
        
        # Cria nova mensagem
        nova_mensagem = {
            "id": len(banco["mensagens"]) + 1,
            "timestamp": data_info,
            "remetente": None,
            "categoria": categoria,
            "contexto": dados_processados.get("contexto", ""),
            "mudanca_chave": dados_processados.get("mudanca_chave", ""),
            "mensagem_original": mensagem,
            "projeto": projeto_id,
            "lesson_learned": lesson_learned,
            "mensagem_hash": mensagem_hash
        }
        
        # Adiciona à lista
        banco["mensagens"].append(nova_mensagem)
        
        # Atualiza estatísticas
        banco["estatisticas"]["total_mensagens"] = len(banco["mensagens"])
        banco["estatisticas"]["ultima_atualizacao"] = datetime.now().isoformat()
        
        # Salva no Dropbox
        if salvar_banco_dropbox(banco):
            print("✅ Mensagem salva no Dropbox com sucesso!")
            return True, "Informação registrada com sucesso!"
        else:
            return False, "Erro ao salvar no banco de dados"
        
    except Exception as e:
        print(f"Erro ao salvar mensagem: {e}")
        return False, f"Erro ao processar a mensagem: {str(e)}"

def exportar_para_csv(projeto_id=None):
    """
    Exporta dados para CSV sem usar pandas
    """
    try:
        banco = carregar_banco_dropbox()
        mensagens = banco.get("mensagens", [])
        
        if projeto_id:
            mensagens = [msg for msg in mensagens if msg.get("projeto") == projeto_id]
        
        if not mensagens:
            return None, "Nenhum dado encontrado para exportar"
        
        # Criar arquivo CSV
        if projeto_id:
            nome_arquivo = f"mensagens_projeto_{projeto_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
        else:
            nome_arquivo = f"mensagens_completo_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
        
        # Definir cabeçalhos
        campos = ['id', 'timestamp', 'categoria', 'contexto', 'mudanca_chave', 'mensagem_original', 'projeto', 'lesson_learned']
        
        with open(nome_arquivo, 'w', newline='', encoding='utf-8') as arquivo:
            writer = csv.DictWriter(arquivo, fieldnames=campos)
            writer.writeheader()
            
            for mensagem in mensagens:
                # Filtrar apenas os campos que queremos
                linha = {campo: mensagem.get(campo, '') for campo in campos}
                writer.writerow(linha)
        
        return nome_arquivo, f"Exportação concluída: {len(mensagens)} registros"
        
    except Exception as e:
        return None, f"Erro na exportação: {str(e)}"

def obter_estatisticas_banco(projeto_id=None):
    """
    Obtém estatísticas do banco de dados sem pandas
    """
    try:
        banco = carregar_banco_dropbox()
        mensagens = banco.get("mensagens", [])
        
        if projeto_id:
            mensagens = [msg for msg in mensagens if msg.get("projeto") == projeto_id]
        
        # Por categoria
        categorias = {}
        for msg in mensagens:
            cat = msg.get("categoria", "Outros")
            categorias[cat] = categorias.get(cat, 0) + 1
        
        # Converter para lista de dicionários
        por_categoria = [{"categoria": k, "quantidade": v} for k, v in categorias.items()]
        
        # Lessons Learned
        lessons_learned = sum(1 for msg in mensagens if msg.get("lesson_learned") == "sim")
        
        return {
            'total': len(mensagens),
            'por_categoria': por_categoria,
            'lessons_learned': lessons_learned,
            'projeto': projeto_id if projeto_id else 'Todos os projetos'
        }
        
    except Exception as e:
        return {'erro': str(e)}

class DBAnalyzer:
    def __init__(self, api_key):
        self.api_key = api_key
        self.api_url = "https://api.deepseek.com/v1/chat/completions"
        self.headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
    
    def extract_db_schema(self):
        return """
        BANCO DE DADOS DE MENSAGENS DE PROJETOS:

        TABELA: mensagens
        - id: identificador único
        - timestamp: data e hora
        - categoria: categoria da informação
        - contexto: contexto da informação
        - mudanca_chave: mudança importante
        - mensagem_original: texto original
        - projeto: ID do projeto
        - lesson_learned: se é lesson learned
        """
    
    def extract_data_samples(self, projeto_id=None):
        try:
            banco = carregar_banco_dropbox()
            mensagens = banco.get("mensagens", [])
            
            if projeto_id:
                mensagens = [msg for msg in mensagens if msg.get("projeto") == projeto_id]
            
            if not mensagens:
                return "Nenhuma mensagem encontrada para análise."
            
            data_samples = f"AMOSTRAS DE DADOS ({len(mensagens)} mensagens):\n\n"
            
            for i, msg in enumerate(mensagens[:5]):  # Limitar a 5 amostras
                data_samples += f"MENSAGEM {i+1}:\n"
                data_samples += f"  Projeto: {msg.get('projeto', 'N/A')}\n"
                data_samples += f"  Categoria: {msg.get('categoria', 'N/A')}\n"
                data_samples += f"  Contexto: {msg.get('contexto', 'N/A')}\n"
                data_samples += f"  Mudança Chave: {msg.get('mudanca_chave', 'N/A')}\n"
                data_samples += f"  Lesson Learned: {msg.get('lesson_learned', 'não')}\n"
                data_samples += f"  Data: {msg.get('timestamp', 'N/A')}\n\n"
            
            return data_samples
            
        except Exception as e:
            return f"Erro ao carregar dados: {str(e)}"
    
    def execute_query(self, query_type, projeto_id=None):
        try:
            banco = carregar_banco_dropbox()
            mensagens = banco.get("mensagens", [])
            
            if projeto_id:
                mensagens = [msg for msg in mensagens if msg.get("projeto") == projeto_id]
            
            if query_type == "count_total":
                return len(mensagens)
            
            elif query_type == "count_by_category":
                categorias = {}
                for msg in mensagens:
                    cat = msg.get("categoria", "Outros")
                    categorias[cat] = categorias.get(cat, 0) + 1
                return [{"categoria": k, "count": v} for k, v in categorias.items()]
            
            elif query_type == "count_lessons_learned":
                return sum(1 for msg in mensagens if msg.get("lesson_learned") == "sim")
            
            return None
        except:
            return None
    
    def ask_question(self, question, projeto_id=None):
        schema = self.extract_db_schema()
        samples = self.extract_data_samples(projeto_id)
        
        # Consultas básicas
        question_lower = question.lower()
        
        if "quantas mensagens" in question_lower:
            count = self.execute_query("count_total", projeto_id)
            if count is not None:
                return f"Existem {count} mensagens{' neste projeto' if projeto_id else ' no total'}."
        
        if "categorias" in question_lower and "quantas" in question_lower:
            categorias = self.execute_query("count_by_category", projeto_id)
            if categorias:
                resposta = "Distribuição por categorias:\n"
                for item in categorias:
                    resposta += f"- {item['categoria']}: {item['count']} mensagens\n"
                return resposta
        
        if "lessons learned" in question_lower or "lições aprendidas" in question_lower:
            count = self.execute_query("count_lessons_learned", projeto_id)
            if count is not None:
                return f"Existem {count} Lessons Learned{' neste projeto' if projeto_id else ' no total'}."
        
        # Consulta à API DeepSeek para perguntas complexas
        prompt = f"""
        Baseado nos dados abaixo, responda a pergunta:

        {schema}
        
        {samples}

        Pergunta: {question}

        Responda de forma clara e direta baseando-se apenas nos dados fornecidos:
        """
        
        payload = {
            "model": "deepseek-chat",
            "messages": [
                {"role": "system", "content": "Você é um assistente especializado em análise de dados de projetos de construção civil. Responda sempre em portugês."},
                {"role": "user", "content": prompt}
            ],
            "temperature": 0.1,
            "max_tokens": 1000
        }
        
        try:
            response = requests.post(self.api_url, headers=self.headers, json=payload, timeout=30)
            response.raise_for_status()
            result = response.json()
            return result['choices'][0]['message']['content']
        except Exception as e:
            return f"Desculpe, não consegui processar sua pergunta no momento. Erro: {str(e)}"

# Inicialização
print("🔄 Inicializando aplicação...")
PROJETOS = carregar_projetos_csv()
db_analyzer = DBAnalyzer(DEEPSEEK_API_KEY)

# Inicializar banco no Dropbox se não existir
carregar_banco_dropbox()

print("✅ Aplicação inicializada")
# HTML para a página principal com seleção de projeto no menu
HTML_BASE = '''
<!DOCTYPE html>
<html lang="pt-BR">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Pergunta pra Pinho</title>
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
            display: block;
            margin: 0 auto;
        }
        .export-section {
            margin-top: 20px;
            padding: 15px;
            background-color: #34495e;
            border-radius: 5px;
        }
        .export-section h3 {
            margin-top: 0;
            margin-bottom: 10px;
            font-size: 14px;
        }
        .export-buttons {
            display: flex;
            flex-direction: column;
            gap: 8px;
        }
        .export-button {
            padding: 8px 12px;
            background-color: #3498db;
            color: white;
            border: none;
            border-radius: 4px;
            cursor: pointer;
            font-size: 12px;
            transition: background-color 0.3s;
        }
        .export-button:hover {
            background-color: #2980b9;
        }
        .export-button:disabled {
            background-color: #95a5a6;
            cursor: not-allowed;
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
            transition: background-color 0.3s;
        }
        button:hover {
            background-color: #2980b9;
        }
        button:disabled {
            background-color: #95a5a6;
            cursor: not-allowed;
        }
        button.processing {
            background-color: #f39c12;
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
            transition: all 0.3s;
        }
        .option-button.selected {
            background-color: #3498db;
            color: white;
            border-color: #2980b9;
        }
        .option-button:disabled {
            background-color: #bdc3c7;
            cursor: not-allowed;
            opacity: 0.6;
        }
        .lesson-learned {
            background-color: #fff3cd;
            border-left: 4px solid #ffc107;
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
        .warning-message {
            color: #f39c12;
            font-weight: bold;
        }
        .lesson-learned-badge {
            background-color: #ffc107;
            color: #000;
            padding: 2px 8px;
            border-radius: 12px;
            font-size: 12px;
            margin-left: 10px;
        }
        .no-projeto-selecionado {
            text-align: center;
            padding: 40px;
            background-color: #f8f9fa;
            border-radius: 5px;
            color: #6c757d;
        }
        .chat-messages {
            flex: 1;
            overflow-y: auto;
            margin-bottom: 20px;
            padding: 10px;
            border: 1px solid #ddd;
            border-radius: 5px;
        }
        .chat-input {
            display: flex;
            gap: 10px;
        }
        .examples {
            background-color: #f8f9fa;
            padding: 15px;
            border-radius: 5px;
            margin-top: 20px;
        }
        .examples h3 {
            margin-top: 0;
        }
        .examples ul {
            padding-left: 20px;
        }
        .examples li {
            margin-bottom: 5px;
            cursor: pointer;
            color: #3498db;
        }
        .examples li:hover {
            text-decoration: underline;
        }
        .loading {
            color: #666;
            font-style: italic;
        }
        .duplicate-warning {
            background-color: #fff3cd;
            border-left: 4px solid #ffc107;
            padding: 10px;
            margin: 10px 0;
            border-radius: 4px;
            display: none;
        }
        .export-status {
            margin-top: 10px;
            padding: 10px;
            border-radius: 4px;
            text-align: center;
            font-size: 14px;
        }
        .export-success {
            background-color: #d4edda;
            color: #155724;
            border: 1px solid #c3e6cb;
        }
        .export-error {
            background-color: #f8d7da;
            color: #721c24;
            border: 1px solid #f5c6cb;
        }
    </style>
</head>
<body>
    <div class="sidebar">
        <div class="sidebar-content">
            <h2>PPP</h2>
            
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

            <div class="export-section">
                <h3>Backup & Exportação</h3>
                <div class="export-buttons">
                    <button class="export-button" onclick="fazerBackup()" id="btn-backup">
                        ☁️ Fazer Backup
                    </button>
                    <button class="export-button" onclick="restaurarBackup()" id="btn-restore">
                        📥 Restaurar Backup
                    </button>
                    <button class="export-button" onclick="exportarDados('projeto')" id="btn-export-projeto" disabled>
                        📤 Exportar Projeto
                    </button>
                    <button class="export-button" onclick="exportarDados('completo')" id="btn-export-completo">
                        💾 Exportar Tudo
                    </button>
                </div>
                <div id="backup-status" class="export-status hidden"></div>
            </div>
        </div>
        
        <div class="sidebar-image">
            <img src="/static/PPP.png" alt="">
        </div>
    </div>

    <div class="main-content">
        <div class="container">
            <header>
                <h1 id="titulo-pagina">Pergunta pra Pinho</h1>
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
        // Variáveis globais
        let projetoSelecionado = null;
        let paginaAtual = 'entrada';
        let entradaState = {
            currentStep: 0,
            categoria: '',
            subcategoria: '',
            dataInfo: '',
            isLessonLearned: false,
            isProcessing: false
        };
        
        // Carregar projetos quando a página carregar
        window.onload = function() {
            carregarListaProjetos();
        };
        
        function carregarListaProjetos() {
            fetch('/api/projetos')
                .then(response => response.json())
                .then(data => {
                    if (data.success) {
                        const select = document.getElementById('projeto-select');
                        // Limpar opções existentes (exceto a primeira)
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
            const btnExportProjeto = document.getElementById('btn-export-projeto');
            const btnBackup = document.getElementById('btn-backup');
            const btnRestore = document.getElementById('btn-restore');
            
            if (projetoSelecionado) {
                statusDiv.className = 'projeto-selecionado';
                statusDiv.innerHTML = `Projeto: <strong>${projetoSelecionado.nome}</strong>`;
                select.value = projetoSelecionado.id;
                if (btnExportProjeto) btnExportProjeto.disabled = false;
                if (btnBackup) btnBackup.disabled = false;
                if (btnRestore) btnRestore.disabled = false;
            } else {
                statusDiv.className = 'projeto-nao-selecionado';
                statusDiv.textContent = 'Nenhum projeto selecionado';
                select.value = '';
                if (btnExportProjeto) btnExportProjeto.disabled = true;
                if (btnBackup) btnBackup.disabled = true;
                if (btnRestore) btnRestore.disabled = true;
            }
        }
        
        function carregarPagina(pagina) {
            paginaAtual = pagina;
            
            // Atualizar navegação
            document.querySelectorAll('.sidebar nav a').forEach(link => {
                link.classList.remove('active');
            });
            document.getElementById(`nav-${pagina}`).classList.add('active');
            
            // Carregar conteúdo da página
            fetch(`/api/conteudo/${pagina}`)
                .then(response => response.json())
                .then(data => {
                    if (data.success) {
                        document.getElementById('conteudo-pagina').innerHTML = data.conteudo;
                        document.getElementById('titulo-pagina').textContent = data.titulo;
                        document.getElementById('subtitulo-pagina').textContent = data.subtitulo;
                        
                        // Inicializar a página carregada
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
        
        function fazerBackup() {
            const statusDiv = document.getElementById('backup-status');
            
            if (statusDiv) {
                statusDiv.className = 'export-status';
                statusDiv.textContent = '⏳ Fazendo backup na nuvem...';
                statusDiv.classList.remove('hidden');
            }
            
            fetch('/api/fazer_backup', {
                method: 'POST'
            })
            .then(response => response.json())
            .then(data => {
                if (statusDiv) {
                    if (data.success) {
                        statusDiv.className = 'export-status export-success';
                        statusDiv.textContent = '✅ ' + data.message;
                    } else {
                        statusDiv.className = 'export-status export-error';
                        statusDiv.textContent = '❌ ' + data.message;
                    }
                }
            })
            .catch(error => {
                console.error('Erro no backup:', error);
                if (statusDiv) {
                    statusDiv.className = 'export-status export-error';
                    statusDiv.textContent = '❌ Erro no backup';
                }
            });
        }

        function restaurarBackup() {
            if (!confirm('⚠️ Atenção! Isso substituirá o banco de dados local pelo da nuvem. Continuar?')) {
                return;
            }
            
            const statusDiv = document.getElementById('backup-status');
            
            if (statusDiv) {
                statusDiv.className = 'export-status';
                statusDiv.textContent = '⏳ Restaurando backup...';
                statusDiv.classList.remove('hidden');
            }
            
            fetch('/api/restaurar_backup', {
                method: 'POST'
            })
            .then(response => response.json())
            .then(data => {
                if (statusDiv) {
                    if (data.success) {
                        statusDiv.className = 'export-status export-success';
                        statusDiv.textContent = '✅ ' + data.message;
                        // Recarrega a página para refletir os dados restaurados
                        setTimeout(() => location.reload(), 2000);
                    } else {
                        statusDiv.className = 'export-status export-error';
                        statusDiv.textContent = '❌ ' + data.message;
                    }
                }
            })
            .catch(error => {
                console.error('Erro na restauração:', error);
                if (statusDiv) {
                    statusDiv.className = 'export-status export-error';
                    statusDiv.textContent = '❌ Erro na restauração';
                }
            });
        }
        
        function exportarDados(tipo) {
            const projetoId = tipo === 'projeto' && projetoSelecionado ? projetoSelecionado.id : null;
            const statusDiv = document.getElementById('backup-status');
            
            if (statusDiv) {
                statusDiv.className = 'export-status';
                statusDiv.textContent = '⏳ Gerando arquivo...';
                statusDiv.classList.remove('hidden');
            }
            
            fetch('/api/exportar_csv', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({ projeto_id: projetoId })
            })
            .then(response => response.json())
            .then(data => {
                if (data.success) {
                    if (statusDiv) {
                        statusDiv.className = 'export-status export-success';
                        statusDiv.textContent = '✅ ' + data.message;
                    }
                    
                    // Download automático do arquivo
                    window.open(`/api/download_csv/${data.arquivo}`, '_blank');
                    
                } else {
                    if (statusDiv) {
                        statusDiv.className = 'export-status export-error';
                        statusDiv.textContent = '❌ ' + data.message;
                    }
                }
            })
            .catch(error => {
                console.error('Erro na exportação:', error);
                if (statusDiv) {
                    statusDiv.className = 'export-status export-error';
                    statusDiv.textContent = '❌ Erro na exportação';
                }
            });
        }
        
        // ===== FUNÇÕES PARA ENTRADA DE INFORMAÇÃO =====
        function inicializarEntrada() {
            // Inicializar a data atual
            const now = new Date();
            const localDateTime = now.toISOString().slice(0, 16);
            const dataInput = document.getElementById('data-info');
            if (dataInput) dataInput.value = localDateTime;
            
            // Verificar se há projeto selecionado
            const mensagemInicial = document.getElementById('mensagem-inicial');
            if (mensagemInicial) {
                if (projetoSelecionado) {
                    mensagemInicial.textContent = 
                        `Olá! Você está registrando informações para o projeto ${projetoSelecionado.nome}. Selecione a categoria da informação.`;
                    // Mostrar primeira etapa
                    const categoriaStep = document.getElementById('categoria-step');
                    if (categoriaStep) categoriaStep.classList.remove('hidden');
                } else {
                    mensagemInicial.textContent = 
                        'Por favor, selecione um projeto no menu lateral para começar a registrar informações.';
                }
            }
            
            // Resetar estado
            entradaState = {
                currentStep: 0,
                categoria: '',
                subcategoria: '',
                dataInfo: '',
                isLessonLearned: false,
                isProcessing: false
            };
            
            // Adicionar event listener para verificação de duplicatas em tempo real
            const mensagemInput = document.getElementById('mensagem');
            if (mensagemInput) {
                mensagemInput.addEventListener('input', verificarDuplicataEmTempoReal);
            }
        }
        
        // Função para verificar duplicatas em tempo real
        function verificarDuplicataEmTempoReal() {
            if (!projetoSelecionado || !entradaState.categoria) return;
            
            const mensagemInput = document.getElementById('mensagem');
            const mensagem = mensagemInput ? mensagemInput.value.trim() : '';
            const submitButton = document.querySelector('#mensagem-step button');
            const warningDiv = document.getElementById('duplicate-warning');
            
            if (mensagem.length < 5) {
                if (warningDiv) warningDiv.style.display = 'none';
                if (submitButton) submitButton.disabled = true;
                return;
            }
            
            // Verificar duplicata via API
            fetch('/api/verificar_duplicata', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({
                    projeto_id: projetoSelecionado.id,
                    categoria: entradaState.isLessonLearned ? `Lessons learned - ${entradaState.subcategoria}` : entradaState.categoria,
                    mensagem: mensagem
                })
            })
            .then(response => response.json())
            .then(data => {
                if (submitButton) {
                    submitButton.disabled = data.is_duplicata || entradaState.isProcessing;
                    if (data.is_duplicata) {
                        submitButton.innerHTML = '⚠️ Informação Já Registrada';
                    } else {
                        submitButton.innerHTML = 'Registrar Informação';
                    }
                }
                
                if (warningDiv) {
                    if (data.is_duplicata) {
                        warningDiv.style.display = 'block';
                        warningDiv.innerHTML = '⚠️ <strong>Atenção:</strong> Esta informação parece já ter sido registrada anteriormente.';
                    } else {
                        warningDiv.style.display = 'none';
                    }
                }
            })
            .catch(error => {
                console.error('Erro ao verificar duplicata:', error);
            });
        }
        
        // Funções globais para entrada de informação
        window.selectCategory = function(element, selectedCategory) {
            if (!projetoSelecionado || entradaState.isProcessing) return;
            
            // Remover seleção anterior
            const buttons = document.querySelectorAll('#categoria-step .option-button');
            buttons.forEach(button => button.classList.remove('selected'));
            
            // Selecionar nova categoria
            element.classList.add('selected');
            entradaState.categoria = selectedCategory;
            entradaState.isLessonLearned = (selectedCategory === 'Lessons learned');
        };
        
        window.submitCategory = function() {
            if (!projetoSelecionado) {
                alert("Por favor, selecione um projeto primeiro.");
                return;
            }
            
            if (!entradaState.categoria) {
                alert("Por favor, selecione uma categoria.");
                return;
            }
            
            addMessage(`Categoria: ${entradaState.categoria}`, "user");
            document.getElementById('categoria-step').classList.add('hidden');
            
            if (entradaState.isLessonLearned) {
                // Se for Lesson Learned, perguntar a subcategoria
                document.getElementById('subcategoria-step').classList.remove('hidden');
                addMessage("Agora selecione a subcategoria desta Lesson Learned.", "bot");
                entradaState.currentStep = 2;
            } else {
                // Se não for Lesson Learned, ir para a data
                document.getElementById('data-step').classList.remove('hidden');
                addMessage("Agora informe a data da informação. A data atual já está preenchida, mas você pode alterá-la se necessário.", "bot");
                entradaState.currentStep = 3;
            }
        };
        
        window.selectSubCategory = function(element, selectedSubCategory) {
            if (entradaState.isProcessing) return;
            
            // Remover seleção anterior
            const buttons = document.querySelectorAll('#subcategoria-step .option-button');
            buttons.forEach(button => button.classList.remove('selected'));
            
            // Selecionar nova subcategoria
            element.classList.add('selected');
            entradaState.subcategoria = selectedSubCategory;
        };
        
        window.submitSubCategory = function() {
            if (!entradaState.subcategoria) {
                alert("Por favor, selecione uma subcategoria.");
                return;
            }
            
            addMessage(`Subcategoria: ${entradaState.subcategoria}`, "user");
            document.getElementById('subcategoria-step').classList.add('hidden');
            document.getElementById('data-step').classList.remove('hidden');
            addMessage("Agora informe a data da informação. A data atual já está preenchida, mas você pode alterá-la se necessário.", "bot");
            entradaState.currentStep = 3;
        };
        
        window.submitDate = function() {
            if (entradaState.isProcessing) return;
            
            const dataInput = document.getElementById('data-info');
            entradaState.dataInfo = dataInput ? dataInput.value : '';
            
            if (!entradaState.dataInfo) {
                alert("Por favor, informe a data.");
                return;
            }
            
            addMessage(`Data: ${formatDateTime(entradaState.dataInfo)}`, "user");
            document.getElementById('data-step').classList.add('hidden');
            document.getElementById('mensagem-step').classList.remove('hidden');
            addMessage("Por fim, digite a informação que deseja registrar.", "bot");
            entradaState.currentStep = 4;
            
            // Adicionar div de aviso de duplicata se não existir
            if (!document.getElementById('duplicate-warning')) {
                const warningDiv = document.createElement('div');
                warningDiv.id = 'duplicate-warning';
                warningDiv.className = 'duplicate-warning hidden';
                document.getElementById('mensagem-step').insertBefore(warningDiv, document.querySelector('#mensagem-step button'));
            }
            
            // Verificar duplicata inicial
            setTimeout(verificarDuplicataEmTempoReal, 100);
        };
        
        window.submitMessage = function() {
            if (entradaState.isProcessing) return;
            
            const mensagemInput = document.getElementById('mensagem');
            const mensagem = mensagemInput ? mensagemInput.value.trim() : '';
            const submitButton = document.querySelector('#mensagem-step button');
            
            if (!mensagem) {
                alert("Por favor, digite a informação.");
                return;
            }
            
            // Desabilitar botão e mostrar estado de processamento
            entradaState.isProcessing = true;
            if (submitButton) {
                submitButton.disabled = true;
                submitButton.classList.add('processing');
                submitButton.innerHTML = '⏳ Processando...';
            }
            
            // Desabilitar outros botões
            document.querySelectorAll('#input-section button').forEach(btn => {
                if (btn !== submitButton) btn.disabled = true;
            });
            
            addMessage(`Informação: ${mensagem}`, "user");
            
            // Mostrar mensagem de processamento
            addMessage("⏳ Processando e salvando a informação...", "bot");
            
            // Determinar a categoria final
            let categoriaFinal = entradaState.categoria;
            if (entradaState.isLessonLearned) {
                categoriaFinal = `Lessons learned - ${entradaState.subcategoria}`;
            }
            
            // Determinar se é lesson learned
            const lessonLearned = entradaState.isLessonLearned ? 'sim' : 'não';
            
            // Enviar dados para o servidor
            fetch('/api/registrar_mensagem', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({
                    projeto_id: projetoSelecionado.id,
                    categoria: categoriaFinal,
                    data_info: entradaState.dataInfo,
                    mensagem: mensagem,
                    lesson_learned: lessonLearned
                })
            })
            .then(response => response.json())
            .then(data => {
                // Remover mensagem de processamento
                const chatMessages = document.getElementById('chat-messages');
                if (chatMessages && chatMessages.lastChild && chatMessages.lastChild.textContent.includes("Processando")) {
                    chatMessages.removeChild(chatMessages.lastChild);
                }
                
                if (data.success) {
                    const successMsg = entradaState.isLessonLearned 
                        ? "✅ Lesson Learned registrada com sucesso! O contexto foi analisado automaticamente." 
                        : "✅ Informação registrada com sucesso! O contexto foi analisado automaticamente.";
                    
                    addMessage(successMsg, "bot");
                    
                    // Resetar o formulário
                    setTimeout(() => {
                        resetFormEntrada();
                        entradaState.isProcessing = false;
                    }, 1000);
                    
                } else {
                    addMessage(`❌ ${data.message}`, "bot");
                    
                    // Reabilitar botão em caso de erro
                    setTimeout(() => {
                        entradaState.isProcessing = false;
                        if (submitButton) {
                            submitButton.disabled = false;
                            submitButton.classList.remove('processing');
                            submitButton.innerHTML = 'Registrar Informação';
                        }
                        document.querySelectorAll('#input-section button').forEach(btn => {
                            if (btn !== submitButton) btn.disabled = false;
                        });
                    }, 2000);
                }
            })
            .catch(error => {
                addMessage(`❌ Erro ao conectar com o servidor: ${error}`, "bot");
                
                // Reabilitar botão em caso de erro
                setTimeout(() => {
                    entradaState.isProcessing = false;
                    if (submitButton) {
                        submitButton.disabled = false;
                        submitButton.classList.remove('processing');
                        submitButton.innerHTML = 'Registrar Informação';
                    }
                    document.querySelectorAll('#input-section button').forEach(btn => {
                        if (btn !== submitButton) btn.disabled = false;
                    });
                }, 2000);
            });
        };
        
        function resetFormEntrada() {
            const mensagemInput = document.getElementById('mensagem');
            if (mensagemInput) mensagemInput.value = '';
            
            // Resetar seleções
            const categoriaButtons = document.querySelectorAll('#categoria-step .option-button');
            categoriaButtons.forEach(button => {
                button.classList.remove('selected');
                button.disabled = false;
            });
            
            const subcategoriaButtons = document.querySelectorAll('#subcategoria-step .option-button');
            subcategoriaButtons.forEach(button => {
                button.classList.remove('selected');
                button.disabled = false;
            });
            
            // Resetar estado
            entradaState = {
                currentStep: 0,
                categoria: '',
                subcategoria: '',
                dataInfo: '',
                isLessonLearned: false,
                isProcessing: false
            };
            
            // Restaurar data atual
            const now = new Date();
            const localDateTime = now.toISOString().slice(0, 16);
            const dataInput = document.getElementById('data-info');
            if (dataInput) dataInput.value = localDateTime;
            
            // Voltar para a primeira etapa
            document.getElementById('categoria-step').classList.remove('hidden');
            document.getElementById('subcategoria-step').classList.add('hidden');
            document.getElementById('data-step').classList.add('hidden');
            document.getElementById('mensagem-step').classList.add('hidden');
            
            // Esconder aviso de duplicata
            const warningDiv = document.getElementById('duplicate-warning');
            if (warningDiv) warningDiv.style.display = 'none';
            
            // Reabilitar todos os botões
            document.querySelectorAll('#input-section button').forEach(btn => {
                btn.disabled = false;
                btn.classList.remove('processing');
                const originalText = btn.getAttribute('data-original-text') || btn.textContent;
                btn.innerHTML = originalText;
            });
            
            addMessage("Selecione a categoria para registrar nova informação.", "bot");
        }
        
        function addMessage(text, sender) {
            const chatMessages = document.getElementById('chat-messages');
            if (!chatMessages) return;
            
            const messageDiv = document.createElement('div');
            messageDiv.classList.add('message');
            messageDiv.classList.add(sender === 'bot' ? 'bot-message' : 'user-message');
            messageDiv.textContent = text;
            
            chatMessages.appendChild(messageDiv);
            chatMessages.scrollTop = chatMessages.scrollHeight;
        }
        
        function formatDateTime(dateTimeStr) {
            const date = new Date(dateTimeStr);
            return date.toLocaleString('pt-BR');
        }
        
        // ===== FUNÇÕES PARA CONSULTA =====
        function inicializarConsulta() {
            const mensagemInicial = document.querySelector('#chat-messages .bot-message');
            if (mensagemInicial) {
                if (projetoSelecionado) {
                    mensagemInicial.textContent = 
                        `Olá! Sou seu assistente para consulta de informações do projeto ${projetoSelecionado.nome}. ` +
                        `Posso ajudar você a analisar os dados deste projeto. O que gostaria de saber?`;
                } else {
                    mensagemInicial.textContent = 
                        'Olá! Sou seu assistente para consulta de informações do banco de dados. ' +
                        'Selecione um projeto no menu lateral para consultar dados específicos, ou faça perguntas gerais sobre todos os projetos.';
                }
            }
        }
        
        // Funções globais para consulta (mantidas como antes)
        window.handleKeyPress = function(event) {
            if (event.key === 'Enter') {
                askQuestion();
            }
        };

        window.setExample = function(element) {
            const userQuestion = document.getElementById('user-question');
            if (userQuestion) userQuestion.value = element.textContent;
        };

        window.askQuestion = function() {
            const userQuestion = document.getElementById('user-question');
            const question = userQuestion ? userQuestion.value.trim() : '';
            
            if (!question) {
                alert('Por favor, digite uma pergunta.');
                return;
            }

            // Adiciona a pergunta do usuário ao chat
            addMessageConsulta(question, 'user');
            if (userQuestion) userQuestion.value = '';

            // Adiciona mensagem de carregamento
            const loadingId = addMessageConsulta('Analisando sua pergunta...', 'bot', true);

            // Enviar projeto_id se estiver selecionado
            const projetoId = projetoSelecionado ? projetoSelecionado.id : null;

            // Envia a pergunta para o servidor
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
                // Remove a mensagem de carregamento
                removeLoadingMessage(loadingId);

                if (data.success) {
                    addMessageConsulta(data.answer, 'bot');
                } else {
                    addMessageConsulta('❌ Erro: ' + data.message, 'bot');
                }
            })
            .catch(error => {
                removeLoadingMessage(loadingId);
                addMessageConsulta('❌ Erro ao conectar com o servidor: ' + error, 'bot');
            });
        };

        function addMessageConsulta(text, sender, isTemp = false) {
            const chatMessages = document.getElementById('chat-messages');
            if (!chatMessages) return null;
            
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
</body>
</html>
'''

# HTML para a página de entrada de informação
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
                <div class="option-button" onclick="selectCategory(this, 'Resíduos')">Resíduos</div>
                <div class="option-button" onclick="selectCategory(this, 'Outros')">Outros</div>
                <div class="option-button" onclick="selectCategory(this, 'Lessons learned')">Lessons learned</div>

            </div>
            <button onclick="submitCategory()">Enviar</button>
        </div>

        <div id="subcategoria-step" class="input-group hidden">
            <label>Selecione a categoria da Lesson Learned:</label>
            <div class="option-buttons">
                <div class="option-button" onclick="selectCategory(this, 'Informações base')">Informações base</div>
                <div class="option-button" onclick="selectCategory(this, 'Envoltória')">Envoltória</div>
                <div class="option-button" onclick="selectCategory(this, 'Materiais')">Materiais</div>
                <div class="option-button" onclick="selectCategory(this, 'Água')">Água</div>
                <div class="option-button" onclick="selectCategory(this, 'HVAC')">HVAC</div>
                <div class="option-button" onclick="selectCategory(this, 'Elétrica')">Elétrica</div>
                <div class="option-button" onclick="selectCategory(this, 'LEED')">LEED</div>
                <div class="option-button" onclick="selectCategory(this, 'Resíduos')">Resíduos</div>
                <div class="option-button" onclick="selectCategory(this, 'Outros')">Outros</div>
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
'''

# HTML para a página de consulta
HTML_CONSULTA = '''
<div class="chat-container" style="height: 600px; display: flex; flex-direction: column;">
    <div id="chat-messages" class="chat-messages">
        <div class="message bot-message">
            Carregando...
        </div>
    </div>

    <div class="chat-input">
        <input type="text" id="user-question" placeholder="Digite sua pergunta sobre os dados..." onkeypress="handleKeyPress(event)">
        <button onclick="askQuestion()">Enviar</button>
    </div>
</div>

<div class="examples">
    <h3>Exemplos de perguntas:</h3>
    <ul>
        <li onclick="setExample(this)">Quantas mensagens existem no total?</li>
        <li onclick="setExample(this)">Quantas Lessons Learned existem?</li>
        <li onclick="setExample(this)">Quais categorias existem e quantas mensagens têm cada uma?</li>
        <li onclick="setExample(this)">Mostre as mensagens mais recentes</li>
        <li onclick="setExample(this)">Quantas mensagens existem por projeto?</li>
    </ul>
</div>
'''

# Rotas
@app.route('/')
def index():
    return HTML_BASE

@app.route('/static/<path:filename>')
def serve_static(filename):
    try:
        static_dir = os.path.join(os.path.dirname(__file__), 'static')
        return send_from_directory(static_dir, filename)
    except:
        return "Arquivo não encontrado", 404

@app.route('/api/projetos')
def api_projetos():
    return jsonify({'success': True, 'projetos': PROJETOS})

@app.route('/api/selecionar_projeto', methods=['POST'])
def selecionar_projeto():
    data = request.get_json()
    projeto_id = data.get('projeto_id')
    
    projeto = next((p for p in PROJETOS if p['id'] == projeto_id), None)
    if projeto:
        session['projeto_selecionado'] = {'id': projeto['id'], 'nome': projeto['display']}
        return jsonify({'success': True, 'projeto_nome': projeto['display']})
    else:
        return jsonify({'success': False, 'message': 'Projeto não encontrado'})

@app.route('/api/conteudo/<pagina>')
def api_conteudo(pagina):
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
        
        success, message = salvar_mensagem(projeto_id, categoria, data_info, mensagem, lesson_learned)
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
        
        answer = db_analyzer.ask_question(question, projeto_id)
        return jsonify({'success': True, 'answer': answer})
        
    except Exception as e:
        return jsonify({'success': False, 'message': f'Erro: {str(e)}'})

@app.route('/api/exportar_csv', methods=['POST'])
def api_exportar_csv():
    try:
        data = request.get_json()
        projeto_id = data.get('projeto_id')
        
        arquivo, mensagem = exportar_para_csv(projeto_id)
        
        if arquivo:
            return jsonify({
                'success': True,
                'message': mensagem,
                'arquivo': arquivo
            })
        else:
            return jsonify({
                'success': False,
                'message': mensagem
            })
            
    except Exception as e:
        return jsonify({'success': False, 'message': f'Erro: {str(e)}'})

@app.route('/api/download_csv/<filename>')
def api_download_csv(filename):
    try:
        return send_file(filename, as_attachment=True)
    except Exception as e:
        return jsonify({'success': False, 'message': f'Erro ao baixar arquivo: {str(e)}'})

@app.route('/api/estatisticas', methods=['POST'])
def api_estatisticas():
    try:
        data = request.get_json()
        projeto_id = data.get('projeto_id')
        
        estatisticas = obter_estatisticas_banco(projeto_id)
        
        if 'erro' in estatisticas:
            return jsonify({'success': False, 'message': estatisticas['erro']})
        
        return jsonify({
            'success': True,
            'estatisticas': estatisticas
        })
        
    except Exception as e:
        return jsonify({'success': False, 'message': f'Erro: {str(e)}'})

@app.route('/api/fazer_backup', methods=['POST'])
def api_fazer_backup():
    """API para fazer backup na nuvem"""
    try:
        success, message = upload_db_to_dropbox()
        return jsonify({'success': success, 'message': message})
    except Exception as e:
        return jsonify({'success': False, 'message': f'Erro: {str(e)}'})

@app.route('/api/restaurar_backup', methods=['POST'])
def api_restaurar_backup():
    """API para restaurar backup da nuvem"""
    try:
        success, message = download_db_from_dropbox()
        return jsonify({'success': success, 'message': message})
    except Exception as e:
        return jsonify({'success': False, 'message': f'Erro: {str(e)}'})

if __name__ == '__main__':
    debug_mode = os.getenv('FLASK_DEBUG', 'False').lower() == 'true'
    port = int(os.getenv('PORT', 5000))
    print(f"🚀 Servidor iniciado na porta {port}")
    app.run(debug=debug_mode, host='0.0.0.0', port=port)

