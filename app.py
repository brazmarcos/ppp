from flask import Flask, request, jsonify, session
import json
import re
from datetime import datetime
import os
import hashlib
import requests
import csv
import io

# Configuração da API DeepSeek
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "sk-3133a53daa7b44ccabd6805286671f6b")
DEEPSEEK_API_URL = "https://api.deepseek.com/v1/chat/completions"

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "sua_chave_secreta_aqui_producao_12345")

# Configurar para produção
app.config['SESSION_COOKIE_SECURE'] = os.getenv('FLASK_ENV') == 'production'
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'

# Banco de dados em memória
MEMORY_DB = {
    "mensagens": [],
    "projetos": [
        {'id': '1', 'nome': 'Projeto A', 'display': '1 - Projeto A'},
        {'id': '2', 'nome': 'Projeto B', 'display': '2 - Projeto B'},
        {'id': '3', 'nome': 'Projeto C', 'display': '3 - Projeto C'}
    ]
}

def carregar_banco():
    return MEMORY_DB

def salvar_banco(dados):
    global MEMORY_DB
    MEMORY_DB = dados
    return True

def gerar_hash_mensagem(projeto_id, categoria, mensagem):
    conteudo = f"{projeto_id}_{categoria}_{mensagem}".lower().strip()
    return hashlib.md5(conteudo.encode()).hexdigest()

def verificar_duplicata(projeto_id, categoria, mensagem):
    try:
        banco = carregar_banco()
        mensagens = banco.get("mensagens", [])
        mensagem_hash = gerar_hash_mensagem(projeto_id, categoria, mensagem)
        
        for msg in mensagens:
            if msg.get("mensagem_hash") == mensagem_hash:
                return True
        return False
    except:
        return False

def processar_contexto_mensagem(mensagem):
    # Versão simplificada sem API
    return {
        "contexto": "Informação registrada no sistema",
        "mudanca_chave": mensagem[:100] + "..." if len(mensagem) > 100 else mensagem
    }

def salvar_mensagem(projeto_id, categoria, data_info, mensagem, lesson_learned):
    if verificar_duplicata(projeto_id, categoria, mensagem):
        return False, "Esta informação já foi registrada anteriormente."
    
    dados_processados = processar_contexto_mensagem(mensagem)
    mensagem_hash = gerar_hash_mensagem(projeto_id, categoria, mensagem)
    
    try:
        banco = carregar_banco()
        
        nova_mensagem = {
            "id": len(banco["mensagens"]) + 1,
            "timestamp": data_info,
            "categoria": categoria,
            "contexto": dados_processados.get("contexto", ""),
            "mudanca_chave": dados_processados.get("mudanca_chave", ""),
            "mensagem_original": mensagem,
            "projeto": projeto_id,
            "lesson_learned": lesson_learned,
            "mensagem_hash": mensagem_hash
        }
        
        banco["mensagens"].append(nova_mensagem)
        salvar_banco(banco)
        return True, "Informação registrada com sucesso!"
        
    except Exception as e:
        return False, f"Erro: {str(e)}"

def exportar_para_csv(projeto_id=None):
    """Exporta dados para CSV sem usar pandas"""
    try:
        banco = carregar_banco()
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
    """Obtém estatísticas do banco de dados sem pandas"""
    try:
        banco = carregar_banco()
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
            banco = carregar_banco()
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
            banco = carregar_banco()
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
                {"role": "system", "content": "Você é um assistente especializado em análise de dados de projetos de construção civil. Responda sempre em português."},
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
db_analyzer = DBAnalyzer(DEEPSEEK_API_KEY)
PROJETOS = MEMORY_DB["projetos"]
print("✅ Aplicação inicializada")

# HTML simplificado
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
            background: #f5f5f5; 
            color: #333; 
        }
        .container { 
            max-width: 1200px; 
            margin: 0 auto; 
            padding: 20px; 
        }
        .header { 
            background: #2c3e50; 
            color: white; 
            padding: 30px; 
            border-radius: 10px; 
            text-align: center; 
            margin-bottom: 20px;
        }
        .card { 
            background: white; 
            padding: 25px; 
            margin: 20px 0; 
            border-radius: 10px; 
            box-shadow: 0 2px 10px rgba(0,0,0,0.1);
        }
        .message { 
            margin: 15px 0; 
            padding: 15px; 
            border-radius: 8px; 
            border-left: 4px solid;
        }
        .user { 
            background: #e8f5e8; 
            border-left-color: #2ecc71;
            text-align: right;
        }
        .bot { 
            background: #e8f4f8; 
            border-left-color: #3498db;
        }
        input, textarea, select { 
            width: 100%; 
            padding: 12px; 
            margin: 8px 0; 
            border: 1px solid #ddd; 
            border-radius: 5px; 
            box-sizing: border-box;
        }
        button { 
            background: #3498db; 
            color: white; 
            border: none; 
            padding: 12px 25px; 
            border-radius: 5px; 
            cursor: pointer; 
            font-size: 16px;
            margin: 5px;
        }
        button:hover { 
            background: #2980b9; 
        }
        .button-group {
            display: flex;
            gap: 10px;
            flex-wrap: wrap;
            margin: 15px 0;
        }
        .projeto-info {
            background: #27ae60;
            color: white;
            padding: 15px;
            border-radius: 5px;
            margin: 15px 0;
            text-align: center;
        }
        .no-projeto {
            background: #e74c3c;
            color: white;
            padding: 15px;
            border-radius: 5px;
            margin: 15px 0;
            text-align: center;
        }
        .chat-container {
            max-height: 400px;
            overflow-y: auto;
            border: 1px solid #ddd;
            padding: 15px;
            border-radius: 5px;
            margin: 15px 0;
        }
        .export-section {
            background: #34495e;
            color: white;
            padding: 15px;
            border-radius: 5px;
            margin: 15px 0;
        }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>Pergunta pra Pinho</h1>
            <p>Sistema de Gestão de Informações de Projetos</p>
        </div>
        
        <div class="card">
            <h2>Seleção de Projeto</h2>
            <select id="projeto-select">
                <option value="">-- Selecione um Projeto --</option>
            </select>
            <button onclick="selecionarProjeto()">Selecionar Projeto</button>
            <div id="projeto-status"></div>
        </div>

        <div class="card">
            <h2>📝 Entrada de Informação</h2>
            <div id="entrada-section">
                <select id="categoria">
                    <option value="Informações base">Informações base</option>
                    <option value="Envoltória">Envoltória</option>
                    <option value="Materiais">Materiais</option>
                    <option value="Água">Água</option>
                    <option value="HVAC">HVAC</option>
                    <option value="Elétrica">Elétrica</option>
                    <option value="LEED">LEED</option>
                    <option value="Resíduos">Resíduos</option>
                    <option value="Outros">Outros</option>
                    <option value="Lessons learned">Lessons learned</option>
                </select>
                
                <input type="datetime-local" id="data-info">
                
                <select id="lesson-learned">
                    <option value="não">Não é Lesson Learned</option>
                    <option value="sim">É Lesson Learned</option>
                </select>
                
                <textarea id="mensagem" rows="4" placeholder="Digite a informação que deseja registrar..."></textarea>
                
                <button onclick="registrarMensagem()">💾 Registrar Informação</button>
                <div id="registro-status" style="margin-top: 10px;"></div>
            </div>
        </div>

        <div class="card">
            <h2>🔍 Consulta de Dados</h2>
            <div class="chat-container" id="consulta-messages">
                <div class="message bot">
                    <strong>Assistente:</strong> Olá! Faça uma pergunta sobre os dados dos projetos. Exemplo: "Quantas mensagens existem?" ou "Quais categorias temos?"
                </div>
            </div>
            <div style="display: flex; gap: 10px;">
                <input type="text" id="pergunta" placeholder="Digite sua pergunta..." style="flex: 1;">
                <button onclick="fazerPergunta()">📤 Perguntar</button>
            </div>
            
            <div class="button-group">
                <button onclick="setExemplo('Quantas mensagens existem no total?')">📊 Total de Mensagens</button>
                <button onclick="setExemplo('Quantas Lessons Learned existem?')">🎓 Lessons Learned</button>
                <button onclick="setExemplo('Quais categorias existem?')">📂 Categorias</button>
                <button onclick="setExemplo('Mostre as mensagens mais recentes')">🕒 Mensagens Recentes</button>
            </div>
        </div>

        <div class="export-section">
            <h2>📤 Exportação de Dados</h2>
            <div class="button-group">
                <button onclick="exportarDados('projeto')" id="btn-export-projeto" disabled>📁 Exportar Projeto</button>
                <button onclick="exportarDados('completo')">💾 Exportar Tudo</button>
                <button onclick="verEstatisticas()">📈 Ver Estatísticas</button>
            </div>
            <div id="export-status" style="margin-top: 10px;"></div>
        </div>
    </div>

    <script>
        let projetoSelecionado = null;
        
        // Carregar projetos ao iniciar
        document.addEventListener('DOMContentLoaded', function() {
            carregarProjetos();
            // Data atual como padrão
            document.getElementById('data-info').value = new Date().toISOString().slice(0, 16);
        });
        
        function carregarProjetos() {
            fetch('/api/projetos')
                .then(r => r.json())
                .then(data => {
                    const select = document.getElementById('projeto-select');
                    data.projetos.forEach(projeto => {
                        const option = document.createElement('option');
                        option.value = projeto.id;
                        option.textContent = projeto.display;
                        select.appendChild(option);
                    });
                });
        }
        
        function selecionarProjeto() {
            const select = document.getElementById('projeto-select');
            const projetoId = select.value;
            
            if (!projetoId) {
                alert('Por favor, selecione um projeto da lista.');
                return;
            }
            
            fetch('/api/selecionar_projeto', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({ projeto_id: projetoId })
            })
            .then(r => r.json())
            .then(data => {
                if (data.success) {
                    projetoSelecionado = { id: projetoId, nome: data.projeto_nome };
                    document.getElementById('projeto-status').innerHTML = 
                        `<div class="projeto-info">Projeto selecionado: <strong>${data.projeto_nome}</strong></div>`;
                    document.getElementById('btn-export-projeto').disabled = false;
                } else {
                    alert('Erro: ' + data.message);
                }
            });
        }
        
        function registrarMensagem() {
            if (!projetoSelecionado) {
                alert('Selecione um projeto primeiro!');
                return;
            }
            
            const categoria = document.getElementById('categoria').value;
            const dataInfo = document.getElementById('data-info').value;
            const mensagem = document.getElementById('mensagem').value.trim();
            const lessonLearned = document.getElementById('lesson-learned').value;
            
            if (!mensagem) {
                alert('Digite a mensagem!');
                return;
            }
            
            const statusDiv = document.getElementById('registro-status');
            statusDiv.innerHTML = '⏳ Processando...';
            
            fetch('/api/registrar_mensagem', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({
                    projeto_id: projetoSelecionado.id,
                    categoria: categoria,
                    data_info: dataInfo,
                    mensagem: mensagem,
                    lesson_learned: lessonLearned
                })
            })
            .then(r => r.json())
            .then(data => {
                if (data.success) {
                    statusDiv.innerHTML = '✅ ' + data.message;
                    document.getElementById('mensagem').value = '';
                } else {
                    statusDiv.innerHTML = '❌ ' + data.message;
                }
            })
            .catch(error => {
                statusDiv.innerHTML = '❌ Erro ao conectar com o servidor';
            });
        }
        
        function fazerPergunta() {
            if (!projetoSelecionado) {
                alert('Selecione um projeto primeiro!');
                return;
            }
            
            const pergunta = document.getElementById('pergunta').value.trim();
            if (!pergunta) {
                alert('Digite uma pergunta!');
                return;
            }
            
            const messagesDiv = document.getElementById('consulta-messages');
            messagesDiv.innerHTML += `<div class="message user"><strong>Você:</strong> ${pergunta}</div>`;
            
            // Mostrar carregamento
            const loadingDiv = document.createElement('div');
            loadingDiv.className = 'message bot';
            loadingDiv.innerHTML = '<strong>Assistente:</strong> ⏳ Analisando sua pergunta...';
            messagesDiv.appendChild(loadingDiv);
            
            fetch('/api/consultar_dados', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({
                    question: pergunta,
                    projeto_id: projetoSelecionado.id
                })
            })
            .then(r => r.json())
            .then(data => {
                // Remover mensagem de carregamento
                messagesDiv.removeChild(loadingDiv);
                
                if (data.success) {
                    messagesDiv.innerHTML += `<div class="message bot"><strong>Assistente:</strong> ${data.answer}</div>`;
                } else {
                    messagesDiv.innerHTML += `<div class="message bot"><strong>Assistente:</strong> ❌ Erro: ${data.message}</div>`;
                }
                
                document.getElementById('pergunta').value = '';
                messagesDiv.scrollTop = messagesDiv.scrollHeight;
            })
            .catch(error => {
                messagesDiv.removeChild(loadingDiv);
                messagesDiv.innerHTML += `<div class="message bot"><strong>Assistente:</strong> ❌ Erro de conexão</div>`;
                messagesDiv.scrollTop = messagesDiv.scrollHeight;
            });
        }
        
        function setExemplo(pergunta) {
            document.getElementById('pergunta').value = pergunta;
        }
        
        function exportarDados(tipo) {
            const projetoId = tipo === 'projeto' && projetoSelecionado ? projetoSelecionado.id : null;
            const statusDiv = document.getElementById('export-status');
            
            statusDiv.innerHTML = '⏳ Gerando arquivo...';
            
            fetch('/api/exportar_csv', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({ projeto_id: projetoId })
            })
            .then(r => r.json())
            .then(data => {
                if (data.success) {
                    statusDiv.innerHTML = '✅ ' + data.message;
                    // Download automático
                    window.open(`/api/download_csv/${data.arquivo}`, '_blank');
                } else {
                    statusDiv.innerHTML = '❌ ' + data.message;
                }
            })
            .catch(error => {
                statusDiv.innerHTML = '❌ Erro na exportação';
            });
        }
        
        function verEstatisticas() {
            if (!projetoSelecionado) {
                alert('Selecione um projeto primeiro!');
                return;
            }
            
            const projetoId = projetoSelecionado.id;
            const statusDiv = document.getElementById('export-status');
            
            statusDiv.innerHTML = '⏳ Carregando estatísticas...';
            
            fetch('/api/estatisticas', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({ projeto_id: projetoId })
            })
            .then(r => r.json())
            .then(data => {
                if (data.success) {
                    const stats = data.estatisticas;
                    let html = `<div style="background: white; color: black; padding: 15px; border-radius: 5px; margin-top: 10px;">
                        <h3>📊 Estatísticas - ${stats.projeto}</h3>
                        <p><strong>Total de Mensagens:</strong> ${stats.total}</p>
                        <p><strong>Lessons Learned:</strong> ${stats.lessons_learned}</p>
                        <p><strong>Distribuição por Categoria:</strong></p>
                        <ul>`;
                    
                    stats.por_categoria.forEach(cat => {
                        html += `<li>${cat.categoria}: ${cat.quantidade} mensagens</li>`;
                    });
                    
                    html += `</ul></div>`;
                    statusDiv.innerHTML = html;
                } else {
                    statusDiv.innerHTML = '❌ ' + data.message;
                }
            })
            .catch(error => {
                statusDiv.innerHTML = '❌ Erro ao carregar estatísticas';
            });
        }
        
        // Enter para enviar pergunta
        document.getElementById('pergunta').addEventListener('keypress', function(e) {
            if (e.key === 'Enter') {
                fazerPergunta();
            }
        });
    </script>
</body>
</html>
'''

# Rotas
@app.route('/')
def index():
    return HTML_BASE

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

@app.route('/api/registrar_mensagem', methods=['POST'])
def registrar_mensagem():
    data = request.get_json()
    projeto_id = data.get('projeto_id')
    categoria = data.get('categoria')
    data_info = data.get('data_info')
    mensagem = data.get('mensagem')
    lesson_learned = data.get('lesson_learned', 'não')
    
    success, message = salvar_mensagem(projeto_id, categoria, data_info, mensagem, lesson_learned)
    return jsonify({'success': success, 'message': message})

@app.route('/api/consultar_dados', methods=['POST'])
def consultar_dados():
    data = request.get_json()
    question = data.get('question')
    projeto_id = data.get('projeto_id')
    
    answer = db_analyzer.ask_question(question, projeto_id)
    return jsonify({'success': True, 'answer': answer})

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

if __name__ == '__main__':
    debug_mode = os.getenv('FLASK_DEBUG', 'False').lower() == 'true'
    port = int(os.getenv('PORT', 5000))
    print(f"🚀 Servidor iniciado na porta {port}")
    app.run(debug=debug_mode, host='0.0.0.0', port=port)
