import sqlite3
from datetime import datetime

DB_NAME = "estacao_lanche.db"

def get_connection():
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_connection()
    c = conn.cursor()
    # Tabelas (Mantive a estrutura igual para não quebrar seu banco atual)
    c.execute('''CREATE TABLE IF NOT EXISTS usuarios (id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT UNIQUE, password_hash TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS clientes (id INTEGER PRIMARY KEY AUTOINCREMENT, nome TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS fiados (id INTEGER PRIMARY KEY AUTOINCREMENT, cliente_id INTEGER, descricao TEXT, valor REAL, data_registro DATETIME, pago BOOLEAN DEFAULT 0, data_pagamento DATETIME, FOREIGN KEY(cliente_id) REFERENCES clientes(id))''')
    c.execute('''CREATE TABLE IF NOT EXISTS caixa_diario (id INTEGER PRIMARY KEY AUTOINCREMENT, data_referencia DATE UNIQUE, valor_vendas_vista REAL, observacao TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS despesas (id INTEGER PRIMARY KEY AUTOINCREMENT, data_despesa DATE, descricao TEXT, valor REAL, categoria TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS pagamentos (id INTEGER PRIMARY KEY AUTOINCREMENT, cliente_id INTEGER, valor REAL, data_pagamento DATETIME, FOREIGN KEY(cliente_id) REFERENCES clientes(id))''')
    conn.commit()
    conn.close()

# --- LÓGICA FINANCEIRA CORRIGIDA ---

def get_saldo_cliente(cliente_id):
    """Calcula a dívida real baseada em (Total Comprado - Total Pago)"""
    conn = get_connection()
    
    # 1. Soma tudo que ele já comprou na vida
    total_compras = conn.execute("SELECT SUM(valor) FROM fiados WHERE cliente_id = ?", (cliente_id,)).fetchone()[0] or 0.0
    
    # 2. Soma tudo que ele já pagou na vida
    total_pago = conn.execute("SELECT SUM(valor) FROM pagamentos WHERE cliente_id = ?", (cliente_id,)).fetchone()[0] or 0.0
    
    conn.close()
    
    # O saldo devedor é a diferença. Se for negativo, ele tem crédito.
    return total_compras - total_pago

def registrar_pagamento_abatimento(cliente_id, valor_pago):
    """Registra o dinheiro e tenta dar baixa visual nos itens antigos"""
    conn = get_connection()
    
    # 1. Registra o pagamento (O dinheiro entrou!)
    conn.execute("INSERT INTO pagamentos (cliente_id, valor, data_pagamento) VALUES (?, ?, datetime('now'))", 
                 (cliente_id, valor_pago))
    
    # 2. Tenta marcar itens antigos como 'pagos' apenas para limpar a lista visualmente
    # (A dívida real já foi resolvida no passo 1)
    
    # Pegamos todos os itens abertos
    itens_abertos = conn.execute("SELECT id, valor FROM fiados WHERE cliente_id = ? AND pago = 0 ORDER BY data_registro ASC", (cliente_id,)).fetchall()
    
    # Precisamos saber quanto de "crédito total" esse cliente tem disponível para abater itens
    # Em vez de usar só o valor_pago atual, vamos ver o histórico todo para corrigir erros passados
    total_pago_historico = conn.execute("SELECT SUM(valor) FROM pagamentos WHERE cliente_id = ?", (cliente_id,)).fetchone()[0] or 0.0
    total_itens_baixados = conn.execute("SELECT SUM(valor) FROM fiados WHERE cliente_id = ? AND pago = 1", (cliente_id,)).fetchone()[0] or 0.0
    
    # Saldo disponível para "matar" itens da lista visual
    saldo_para_abater_visual = total_pago_historico - total_itens_baixados
    
    # Arredondamento para evitar bugs de float (ex: 24.9999999)
    saldo_para_abater_visual = round(saldo_para_abater_visual, 2)

    for item in itens_abertos:
        if saldo_para_abater_visual <= 0:
            break
            
        # Se temos saldo suficiente para pagar esse item inteiro
        if saldo_para_abater_visual >= item['valor']:
            conn.execute("UPDATE fiados SET pago = 1, data_pagamento = datetime('now') WHERE id = ?", (item['id'],))
            saldo_para_abater_visual -= item['valor']
        else:
            # Não temos saldo para matar esse item inteiro, então ele fica na lista
            # Mas não tem problema, porque a função get_saldo_cliente garante que o valor "Deve Atualmente" estará certo
            break
            
    conn.commit()
    conn.close()

# --- OUTRAS FUNÇÕES ---

def buscar_clientes_com_divida():
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id, nome FROM clientes")
    clientes = cursor.fetchall()
    conn.close()
    
    lista_final = []
    for cliente in clientes:
        # Usamos a nova função de saldo para garantir precisão
        divida = get_saldo_cliente(cliente['id'])
        # Só adiciona na lista se tiver movimentação ou dívida
        lista_final.append({
            "id": cliente['id'],
            "nome": cliente['nome'],
            "divida_total": divida
        })
        
    # Ordenar quem deve mais primeiro
    return sorted(lista_final, key=lambda x: x['divida_total'], reverse=True)

def buscar_cliente(id):
    conn = get_connection()
    cliente = conn.execute("SELECT * FROM clientes WHERE id = ?", (id,)).fetchone()
    conn.close()
    return cliente

def inserir_cliente(nome):
    conn = get_connection()
    conn.execute("INSERT INTO clientes (nome) VALUES (?)", (nome,))
    conn.commit()
    conn.close()

def inserir_fiado(cliente_id, descricao, valor):
    conn = get_connection()
    conn.execute("INSERT INTO fiados (cliente_id, descricao, valor, data_registro) VALUES (?, ?, ?, datetime('now'))",
                 (cliente_id, descricao, valor))
    conn.commit()
    conn.close()

# No arquivo db.py

def buscar_itens_pendentes(cliente_id):
    """
    Retorna apenas os itens que ainda não foram totalmente cobertos pelos pagamentos.
    Se um item foi parcialmente pago, retorna apenas o valor restante dele.
    """
    conn = get_connection()
    
    # 1. Pega TODOS os fiados (ordenados do mais antigo para o mais novo)
    fiados_todos = conn.execute("SELECT * FROM fiados WHERE cliente_id = ? ORDER BY data_registro ASC", (cliente_id,)).fetchall()
    
    # 2. Pega o TOTAL que o cliente já pagou na vida
    total_pago = conn.execute("SELECT SUM(valor) FROM pagamentos WHERE cliente_id = ?", (cliente_id,)).fetchone()[0] or 0.0
    
    conn.close()
    
    itens_para_exibir = []
    
    # Saldo que temos para "gastar" abatendo as dívidas antigas
    credito_disponivel = total_pago
    
    for item in fiados_todos:
        valor_original = item['valor']
        
        if credito_disponivel >= valor_original:
            # O crédito cobre esse item totalmente. 
            # Ele está pago, então NÃO adicionamos na lista de exibição.
            credito_disponivel -= valor_original
        
        elif credito_disponivel > 0:
            # O crédito paga apenas uma parte deste item (Pagamento Parcial)
            valor_restante = valor_original - credito_disponivel
            
            # Adicionamos um dicionário modificado para a lista
            item_dict = dict(item) # Converte Row para dict
            item_dict['valor_restante'] = valor_restante # O valor que vai aparecer na tela
            item_dict['status'] = 'Parcial'
            itens_para_exibir.append(item_dict)
            
            credito_disponivel = 0 # Gastamos todo o crédito
            
        else:
            # Não tem mais crédito, esse item é dívida total
            item_dict = dict(item)
            item_dict['valor_restante'] = valor_original
            item_dict['status'] = 'Pendente'
            itens_para_exibir.append(item_dict)
            
    # Inverte a lista para mostrar o mais recente no topo (opcional, mas fica melhor na UI)
    return itens_para_exibir[::-1] 

def buscar_ultimos_pagamentos(cliente_id, limite=3):
    conn = get_connection()
    pagamentos = conn.execute(
        "SELECT * FROM pagamentos WHERE cliente_id = ? ORDER BY data_pagamento DESC LIMIT ?", 
        (cliente_id, limite)
    ).fetchall()
    conn.close()
    return pagamentos

def get_dashboard_totals():
    conn = get_connection()
    # Total Fiado Hoje
    fiado_hoje = conn.execute("SELECT SUM(valor) FROM fiados WHERE date(data_registro) = date('now')").fetchone()[0] or 0.0
    # Recebido Hoje
    recebido_fiado_hoje = conn.execute("SELECT SUM(valor) FROM pagamentos WHERE date(data_pagamento) = date('now')").fetchone()[0] or 0.0
    
    # Total na Rua (Calculado corretamente: Total Vendas - Total Pagamentos de todos)
    total_vendas_geral = conn.execute("SELECT SUM(valor) FROM fiados").fetchone()[0] or 0.0
    total_pagos_geral = conn.execute("SELECT SUM(valor) FROM pagamentos").fetchone()[0] or 0.0
    total_rua = total_vendas_geral - total_pagos_geral

    conn.close()
    return {"fiado_hoje": fiado_hoje, "recebido_hoje": recebido_fiado_hoje, "total_rua": total_rua}

def fechar_caixa_dia(valor_venda_vista, observacao=""):
    conn = get_connection()
    data_hoje = datetime.now().strftime('%Y-%m-%d')
    c = conn.cursor()
    c.execute("SELECT id FROM caixa_diario WHERE data_referencia = ?", (data_hoje,))
    exists = c.fetchone()
    if exists:
        c.execute("UPDATE caixa_diario SET valor_vendas_vista = ?, observacao = ? WHERE id = ?", (valor_venda_vista, observacao, exists['id']))
    else:
        c.execute("INSERT INTO caixa_diario (data_referencia, valor_vendas_vista, observacao) VALUES (?, ?, ?)", (data_hoje, valor_venda_vista, observacao))
    conn.commit()
    conn.close()

def inserir_despesa(descricao, valor, categoria, data=None):
    if not data: data = datetime.now().strftime('%Y-%m-%d')
    conn = get_connection()
    conn.execute("INSERT INTO despesas (descricao, valor, categoria, data_despesa) VALUES (?, ?, ?, ?)", (descricao, valor, categoria, data))
    conn.commit()
    conn.close()

# No arquivo db.py

def relatorio_mes(mes, ano):
    conn = get_connection()
    start_date = f"{ano}-{mes:02d}-01"
    end_date = f"{ano}-{mes:02d}-31"
    
    # 1. Vendas totais informadas no fechamento diário (Já inclui tudo: vendas novas + pagamentos de fiado)
    vendas_caixa_total = conn.execute(f"SELECT SUM(valor_vendas_vista) FROM caixa_diario WHERE data_referencia BETWEEN '{start_date}' AND '{end_date}'").fetchone()[0] or 0.0
    
    # 2. Quanto disso foi recuperação de fiado (Apenas para informação, não soma)
    recuperado_fiado = conn.execute(f"SELECT SUM(valor) FROM pagamentos WHERE date(data_pagamento) BETWEEN '{start_date}' AND '{end_date}'").fetchone()[0] or 0.0
    
    # 3. Despesas
    despesas = conn.execute(f"SELECT SUM(valor) FROM despesas WHERE data_despesa BETWEEN '{start_date}' AND '{end_date}'").fetchone()[0] or 0.0
    
    lista_despesas = conn.execute(f"SELECT * FROM despesas WHERE data_despesa BETWEEN '{start_date}' AND '{end_date}' ORDER BY data_despesa DESC").fetchall()
    
    conn.close()
    
    # CORREÇÃO: O Saldo agora é puramente (Caixa Total - Despesas)
    return {
        "entradas_caixa": vendas_caixa_total,
        "recuperado_fiado": recuperado_fiado, # Vamos mostrar só como "Obs"
        "total_saidas": despesas,
        "saldo": vendas_caixa_total - despesas, # Cálculo corrigido
        "lista_despesas": lista_despesas
    }
    
# No final do arquivo db.py

def excluir_cliente_completo(cliente_id):
    conn = get_connection()
    # Apaga tudo relacionado ao cliente para não sobrar lixo
    conn.execute("DELETE FROM fiados WHERE cliente_id = ?", (cliente_id,))
    conn.execute("DELETE FROM pagamentos WHERE cliente_id = ?", (cliente_id,))
    conn.execute("DELETE FROM clientes WHERE id = ?", (cliente_id,))
    conn.commit()
    conn.close()

# No final do arquivo db.py

def get_meses_disponiveis():
    """Retorna uma lista de (mes, ano) que possuem registros no caixa ou despesas"""
    conn = get_connection()
    # Pega datas do caixa e das despesas, une e ordena
    query = """
        SELECT strftime('%m', data_referencia) as mes, strftime('%Y', data_referencia) as ano FROM caixa_diario
        UNION
        SELECT strftime('%m', data_despesa) as mes, strftime('%Y', data_despesa) as ano FROM despesas
        ORDER BY ano DESC, mes DESC
    """
    resultado = conn.execute(query).fetchall()
    conn.close()
    
    # Se não tiver nada, retorna o mês atual pelo menos
    if not resultado:
        hoje = datetime.now()
        return [(f"{hoje.month:02d}", str(hoje.year))]
        
    return [(row[0], row[1]) for row in resultado]

def get_historico_anual():
    """Retorna o lucro líquido de cada mês que teve movimento"""
    meses = get_meses_disponiveis()
    historico = []
    
    for mes_str, ano_str in meses:
        mes = int(mes_str)
        ano = int(ano_str)
        dados = relatorio_mes(mes, ano) # Reusa a função que já existe
        historico.append({
            "mes": mes,
            "ano": ano,
            "lucro": dados['saldo']
        })
    return historico