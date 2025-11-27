from flask import Flask, render_template, request, redirect, url_for, flash
from datetime import datetime
import db

app = Flask(__name__)
app.secret_key = 'segredo_desenvolvimento'

db.init_db()

@app.route("/")
def home():
    return redirect(url_for('dashboard'))

@app.route("/dashboard")
def dashboard():
    totals = db.get_dashboard_totals()
    return render_template("dashboard.html", totals=totals)

@app.route("/clientes")
def clientes():
    lista = db.buscar_clientes_com_divida()
    return render_template("clientes.html", clientes=lista)

@app.route("/cliente/novo", methods=['POST'])
def novo_cliente():
    nome = request.form.get('nome')
    if nome:
        db.inserir_cliente(nome)
        flash('Cliente cadastrado!', 'success')
    return redirect(url_for('clientes'))

@app.route("/fiado/registrar", methods=['GET', 'POST'])
def registrar_fiado():
    if request.method == 'POST':
        cliente_id = request.form.get('cliente_id')
        descricao = request.form.get('descricao')
        valor = float(request.form.get('valor', 0))
        
        if cliente_id and valor > 0:
            db.inserir_fiado(cliente_id, descricao, valor)
            flash('Fiado lançado!', 'success')
            return redirect(url_for('dashboard'))
        
    clientes = db.buscar_clientes_com_divida()
    return render_template("registrar_fiado.html", clientes=clientes)

@app.route("/cliente/<int:cliente_id>")
def ver_cliente(cliente_id):
    cliente = db.buscar_cliente(cliente_id)
    
    itens = db.buscar_itens_pendentes(cliente_id)
    
    pagamentos = db.buscar_ultimos_pagamentos(cliente_id)
    
    total = db.get_saldo_cliente(cliente_id)
    
    return render_template("cliente_detalhe.html", 
                         cliente=cliente, 
                         itens=itens, 
                         pagamentos=pagamentos,
                         total=total)

@app.route("/cliente/<int:cliente_id>/pagar", methods=['POST'])
def pagar_divida(cliente_id):
    valor = float(request.form.get('valor', 0))
    if valor > 0:
        db.registrar_pagamento_abatimento(cliente_id, valor)
        flash('Pagamento registrado!', 'success')
    return redirect(url_for('ver_cliente', cliente_id=cliente_id))

@app.route("/cliente/<int:cliente_id>/excluir", methods=['POST'])
def excluir_cliente(cliente_id):
    db.excluir_cliente_completo(cliente_id)
    flash('Cliente e histórico excluídos com sucesso.', 'success')
    return redirect(url_for('clientes'))

# --- Financeiro (Versão Nova com Histórico) ---

@app.route("/financeiro")
def financeiro():
    # Tenta pegar mês/ano da URL (ex: ?mes=10&ano=2025)
    # Se não tiver, usa a data de hoje
    agora = datetime.now()
    mes = int(request.args.get('mes', agora.month))
    ano = int(request.args.get('ano', agora.year))
    
    # Busca os dados detalhados daquele mês específico
    relatorio = db.relatorio_mes(mes, ano)
    
    # Busca o histórico geral para a lista no final da página
    historico = db.get_historico_anual()
    
    # Nomes dos meses para exibir bonito na tela
    nomes_meses = {1:'Janeiro', 2:'Fevereiro', 3:'Março', 4:'Abril', 5:'Maio', 6:'Junho', 
                   7:'Julho', 8:'Agosto', 9:'Setembro', 10:'Outubro', 11:'Novembro', 12:'Dezembro'}
    
    nome_mes_atual = nomes_meses.get(mes, 'Mês Desconhecido')
    
    return render_template("financeiro.html", 
                         relatorio=relatorio, 
                         historico=historico,
                         mes_atual=mes, 
                         ano_atual=ano,
                         nome_mes=nome_mes_atual)

@app.route("/financeiro/fechar_caixa", methods=['POST'])
def fechar_caixa():
    valor = float(request.form.get('valor', 0))
    obs = request.form.get('obs')
    db.fechar_caixa_dia(valor, obs)
    flash('Caixa do dia fechado/atualizado!', 'success')
    return redirect(url_for('financeiro'))

@app.route("/financeiro/despesa", methods=['POST'])
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