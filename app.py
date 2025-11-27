import os
from flask import Flask, render_template, request, redirect, url_for, flash
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime
from dotenv import load_dotenv
import db

load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "chave_secreta_padrao_dev")

# --- CONFIGURAÇÃO DE LOGIN ---
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login' # Se tentar acessar página protegida, vai pra cá

class User(UserMixin):
    def __init__(self, id, username, password_hash):
        self.id = id
        self.username = username
        self.password_hash = password_hash

@login_manager.user_loader
def load_user(user_id):
    user_data = db.buscar_usuario_por_id(user_id)
    if user_data:
        return User(id=user_data['id'], username=user_data['username'], password_hash=user_data['password_hash'])
    return None

# --- INICIALIZAÇÃO ---
# Cria tabelas no Supabase se não existirem
try:
    db.init_db()
    
    # Cria usuário ADMIN padrão se não existir nenhum
    if not db.buscar_usuario_por_nome('admin'):
        print("Criando usuário admin padrão...")
        senha_hash = generate_password_hash('admin')
        db.criar_usuario('admin', senha_hash)
except Exception as e:
    print(f"Erro ao conectar no DB: {e}")

# --- ROTAS DE LOGIN ---

@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
        
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        
        user_data = db.buscar_usuario_por_nome(username)
        
        if user_data and check_password_hash(user_data['password_hash'], password):
            user_obj = User(id=user_data['id'], username=user_data['username'], password_hash=user_data['password_hash'])
            login_user(user_obj)
            return redirect(url_for('dashboard'))
        else:
            flash('Login inválido', 'error')
            
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))

# --- ROTAS DA APLICAÇÃO (PROTEGIDAS) ---

@app.route("/")
@login_required
def home():
    return redirect(url_for('dashboard'))

@app.route("/dashboard")
@login_required
def dashboard():
    totals = db.get_dashboard_totals()
    return render_template("dashboard.html", totals=totals)

@app.route("/clientes")
@login_required
def clientes():
    lista = db.buscar_clientes_com_divida()
    return render_template("clientes.html", clientes=lista)

@app.route("/cliente/novo", methods=['POST'])
@login_required
def novo_cliente():
    nome = request.form.get('nome')
    if nome:
        db.inserir_cliente(nome)
        flash('Cliente cadastrado!', 'success')
    return redirect(url_for('clientes'))

@app.route("/fiado/registrar", methods=['GET', 'POST'])
@login_required
def registrar_fiado():
    if request.method == 'POST':
        cliente_id = request.form.get('cliente_id')
        descricao = request.form.get('descricao')
        valor = float(request.form.get('valor', 0))
        if cliente_id and valor > 0:
            db.inserir_fiado(cliente_id, descricao, valor)
            flash('Fiado lançado!', 'success')
            return redirect(url_for('registrar_fiado', cliente_id=int(cliente_id)))
    clientes = db.buscar_clientes_com_divida()
    return render_template("registrar_fiado.html", clientes=clientes)

@app.route("/cliente/<int:cliente_id>")
@login_required
def ver_cliente(cliente_id):
    cliente = db.buscar_cliente(cliente_id)
    itens = db.buscar_itens_pendentes(cliente_id)
    pagamentos = db.buscar_ultimos_pagamentos(cliente_id)
    total = db.get_saldo_cliente(cliente_id)
    return render_template("cliente_detalhe.html", cliente=cliente, itens=itens, pagamentos=pagamentos, total=total)

@app.route("/cliente/<int:cliente_id>/pagar", methods=['POST'])
@login_required
def pagar_divida(cliente_id):
    valor = float(request.form.get('valor', 0))
    if valor > 0:
        db.registrar_pagamento_abatimento(cliente_id, valor)
        flash('Pagamento registrado!', 'success')
    return redirect(url_for('ver_cliente', cliente_id=cliente_id))

@app.route("/cliente/<int:cliente_id>/excluir", methods=['POST'])
@login_required
def excluir_cliente(cliente_id):
    db.excluir_cliente_completo(cliente_id)
    flash('Cliente e histórico excluídos.', 'success')
    return redirect(url_for('clientes'))

@app.route("/financeiro")
@login_required
def financeiro():
    agora = datetime.now()
    mes = int(request.args.get('mes', agora.month))
    ano = int(request.args.get('ano', agora.year))
    relatorio = db.relatorio_mes(mes, ano)
    historico = db.get_historico_anual()
    nomes_meses = {1:'Janeiro', 2:'Fevereiro', 3:'Março', 4:'Abril', 5:'Maio', 6:'Junho', 7:'Julho', 8:'Agosto', 9:'Setembro', 10:'Outubro', 11:'Novembro', 12:'Dezembro'}
    return render_template("financeiro.html", relatorio=relatorio, historico=historico, mes_atual=mes, ano_atual=ano, nome_mes=nomes_meses.get(mes, 'Mês'))

@app.route("/financeiro/fechar_caixa", methods=['POST'])
@login_required
def fechar_caixa():
    try:
        dinheiro = float(request.form.get('dinheiro', '0').replace(',', '.'))
        moeda = float(request.form.get('moeda', '0').replace(',', '.'))
        cartao = float(request.form.get('cartao', '0').replace(',', '.'))
        pix = float(request.form.get('pix', '0').replace(',', '.'))
    except ValueError:
        flash("Os valores de caixa devem ser números válidos.", "error")
        return redirect(url_for('financeiro'))

    db.fechar_caixa_dia(dinheiro, moeda, cartao, pix)
    flash('Caixa detalhado atualizado!', 'success')
    return redirect(url_for('financeiro'))

@app.route("/perfil/alterar_senha", methods=['GET', 'POST'])
@login_required
def alterar_senha():
    if request.method == 'POST':
        senha_atual = request.form.get('senha_atual')
        nova_senha = request.form.get('nova_senha')
        confirmacao_senha = request.form.get('confirmacao_senha')

        # 1. Verificar a Senha Atual
        user_data = db.buscar_usuario_por_id(current_user.id)
        if not check_password_hash(user_data['password_hash'], senha_atual):
            flash('Senha atual incorreta!', 'error')
            return redirect(url_for('alterar_senha'))

        # 2. Verificar se as novas senhas batem
        if nova_senha != confirmacao_senha:
            flash('A nova senha e a confirmação não coincidem.', 'error')
            return redirect(url_for('alterar_senha'))
            
        # 3. Verificar se a senha tem o tamanho mínimo
        if len(nova_senha) < 6:
            flash('A nova senha deve ter no mínimo 6 caracteres.', 'error')
            return redirect(url_for('alterar_senha'))
        
        # 4. Hashear e Salvar
        novo_hash = generate_password_hash(nova_senha)
        db.atualizar_senha_usuario(current_user.id, novo_hash)
        
        flash('Sua senha foi atualizada com sucesso!', 'success')
        return redirect(url_for('dashboard'))
        
    return render_template('alterar_senha.html') 

@app.route("/financeiro/despesa", methods=['POST'])
@login_required
def nova_despesa():
    desc = request.form.get('descricao')
    valor = float(request.form.get('valor', 0))
    cat = request.form.get('categoria')
    if valor > 0:
        db.inserir_despesa(desc, valor, cat)
        flash('Despesa lançada', 'success')
    return redirect(url_for('financeiro'))

if __name__ == '__main__':
    app.run(host="0.0.0.0", port=5000, debug=True)