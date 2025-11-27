import os
import psycopg2
from psycopg2.extras import RealDictCursor
from datetime import datetime
from dotenv import load_dotenv

# Carrega as senhas do arquivo .env
load_dotenv()

def get_connection():
    """Conecta no Supabase usando a URL do .env"""
    url = os.getenv("DATABASE_URL")
    if not url:
        raise ValueError("A variável DATABASE_URL não foi definida no arquivo .env")
    
    conn = psycopg2.connect(url, cursor_factory=RealDictCursor)
    return conn

def init_db():
    """Cria as tabelas no PostgreSQL (Sintaxe ajustada para Postgres)"""
    conn = get_connection()
    c = conn.cursor()
    
    # Usuários
    c.execute('''CREATE TABLE IF NOT EXISTS usuarios 
                 (id SERIAL PRIMARY KEY, username TEXT UNIQUE, password_hash TEXT)''')
    
    # Clientes
    c.execute('''CREATE TABLE IF NOT EXISTS clientes 
                 (id SERIAL PRIMARY KEY, nome TEXT)''')
    
    # Fiados
    c.execute('''CREATE TABLE IF NOT EXISTS fiados 
                 (id SERIAL PRIMARY KEY, cliente_id INTEGER, 
                  descricao TEXT, valor REAL, data_registro TIMESTAMP, 
                  pago BOOLEAN DEFAULT FALSE, data_pagamento TIMESTAMP,
                  FOREIGN KEY(cliente_id) REFERENCES clientes(id))''')
    
    # Caixa Diario
    c.execute('''CREATE TABLE IF NOT EXISTS caixa_diario 
                 (id SERIAL PRIMARY KEY, data_referencia DATE UNIQUE, 
                  valor_vendas_vista REAL, observacao TEXT)''')
    
    # Despesas
    c.execute('''CREATE TABLE IF NOT EXISTS despesas 
                 (id SERIAL PRIMARY KEY, data_despesa DATE, 
                  descricao TEXT, valor REAL, categoria TEXT)''')
    
    # Pagamentos
    c.execute('''CREATE TABLE IF NOT EXISTS pagamentos 
                 (id SERIAL PRIMARY KEY, cliente_id INTEGER, 
                  valor REAL, data_pagamento TIMESTAMP,
                  FOREIGN KEY(cliente_id) REFERENCES clientes(id))''')

    conn.commit()
    conn.close()

# --- FUNÇÕES DE USUÁRIO (LOGIN) ---

def criar_usuario(username, password_hash):
    conn = get_connection()
    try:
        conn.cursor().execute("INSERT INTO usuarios (username, password_hash) VALUES (%s, %s)", (username, password_hash))
        conn.commit()
    except Exception as e:
        print(f"Erro ao criar usuário: {e}")
    finally:
        conn.close()

def buscar_usuario_por_nome(username):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM usuarios WHERE username = %s", (username,))
    user = cur.fetchone()
    conn.close()
    return user

def buscar_usuario_por_id(user_id):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM usuarios WHERE id = %s", (user_id,))
    user = cur.fetchone()
    conn.close()
    return user

# --- LÓGICA FINANCEIRA ---

def get_saldo_cliente(cliente_id):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT SUM(valor) as total FROM fiados WHERE cliente_id = %s", (cliente_id,))
    res_compra = cur.fetchone()
    total_compras = res_compra['total'] if res_compra and res_compra['total'] else 0.0
    
    cur.execute("SELECT SUM(valor) as total FROM pagamentos WHERE cliente_id = %s", (cliente_id,))
    res_pago = cur.fetchone()
    total_pago = res_pago['total'] if res_pago and res_pago['total'] else 0.0
    
    conn.close()
    return total_compras - total_pago

def registrar_pagamento_abatimento(cliente_id, valor_pago):
    conn = get_connection()
    cur = conn.cursor()
    
    # 1. Registrar pagamento
    cur.execute("INSERT INTO pagamentos (cliente_id, valor, data_pagamento) VALUES (%s, %s, NOW())", 
                 (cliente_id, valor_pago))
    
    # 2. Baixa visual (Item por item)
    cur.execute("SELECT id, valor FROM fiados WHERE cliente_id = %s AND pago = FALSE ORDER BY data_registro ASC", (cliente_id,))
    itens_abertos = cur.fetchall()
    
    # Calcula saldo histórico disponível
    cur.execute("SELECT SUM(valor) as t FROM pagamentos WHERE cliente_id = %s", (cliente_id,))
    res_tot = cur.fetchone()
    total_pago_historico = res_tot['t'] if res_tot['t'] else 0.0
    
    cur.execute("SELECT SUM(valor) as t FROM fiados WHERE cliente_id = %s AND pago = TRUE", (cliente_id,))
    res_baix = cur.fetchone()
    total_itens_baixados = res_baix['t'] if res_baix['t'] else 0.0
    
    saldo_visual = round(total_pago_historico - total_itens_baixados, 2)

    for item in itens_abertos:
        if saldo_visual <= 0:
            break
        if saldo_visual >= item['valor']:
            cur.execute("UPDATE fiados SET pago = TRUE, data_pagamento = NOW() WHERE id = %s", (item['id'],))
            saldo_visual -= item['valor']
        else:
            break
            
    conn.commit()
    conn.close()

# --- CLIENTES E FIADOS ---

def buscar_clientes_com_divida():
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT id, nome FROM clientes")
    clientes = cur.fetchall()
    conn.close()
    
    lista_final = []
    for cliente in clientes:
        divida = get_saldo_cliente(cliente['id'])
        lista_final.append({
            "id": cliente['id'],
            "nome": cliente['nome'],
            "divida_total": divida
        })
    return sorted(lista_final, key=lambda x: x['divida_total'], reverse=True)

def buscar_cliente(id):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM clientes WHERE id = %s", (id,))
    cliente = cur.fetchone()
    conn.close()
    return cliente

def inserir_cliente(nome):
    conn = get_connection()
    conn.cursor().execute("INSERT INTO clientes (nome) VALUES (%s)", (nome,))
    conn.commit()
    conn.close()

def inserir_fiado(cliente_id, descricao, valor):
    conn = get_connection()
    conn.cursor().execute("INSERT INTO fiados (cliente_id, descricao, valor, data_registro) VALUES (%s, %s, %s, NOW())",
                 (cliente_id, descricao, valor))
    conn.commit()
    conn.close()

def buscar_itens_pendentes(cliente_id):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM fiados WHERE cliente_id = %s ORDER BY data_registro ASC", (cliente_id,))
    fiados_todos = cur.fetchall()
    
    cur.execute("SELECT SUM(valor) as t FROM pagamentos WHERE cliente_id = %s", (cliente_id,))
    res = cur.fetchone()
    total_pago = res['t'] if res and res['t'] else 0.0
    conn.close()
    
    itens_para_exibir = []
    credito_disponivel = total_pago
    
    for item in fiados_todos:
        valor_original = item['valor']
        if credito_disponivel >= valor_original:
            credito_disponivel -= valor_original
        elif credito_disponivel > 0:
            valor_restante = valor_original - credito_disponivel
            item['valor_restante'] = valor_restante
            item['status'] = 'Parcial'
            itens_para_exibir.append(item)
            credito_disponivel = 0
        else:
            item['valor_restante'] = valor_original
            item['status'] = 'Pendente'
            itens_para_exibir.append(item)
            
    return itens_para_exibir[::-1]

def buscar_ultimos_pagamentos(cliente_id, limite=3):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM pagamentos WHERE cliente_id = %s ORDER BY data_pagamento DESC LIMIT %s", (cliente_id, limite))
    pagamentos = cur.fetchall()
    conn.close()
    return pagamentos

def excluir_cliente_completo(cliente_id):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("DELETE FROM fiados WHERE cliente_id = %s", (cliente_id,))
    cur.execute("DELETE FROM pagamentos WHERE cliente_id = %s", (cliente_id,))
    cur.execute("DELETE FROM clientes WHERE id = %s", (cliente_id,))
    conn.commit()
    conn.close()

# --- DASHBOARD E FINANCEIRO ---

def get_dashboard_totals():
    conn = get_connection()
    cur = conn.cursor()
    
    cur.execute("SELECT SUM(valor) as t FROM fiados WHERE DATE(data_registro) = CURRENT_DATE")
    res = cur.fetchone()
    fiado_hoje = res['t'] if res and res['t'] else 0.0
    
    cur.execute("SELECT SUM(valor) as t FROM pagamentos WHERE DATE(data_pagamento) = CURRENT_DATE")
    res2 = cur.fetchone()
    recebido_hoje = res2['t'] if res2 and res2['t'] else 0.0
    
    cur.execute("SELECT SUM(valor) as t FROM fiados")
    v_total = cur.fetchone()['t'] or 0.0
    cur.execute("SELECT SUM(valor) as t FROM pagamentos")
    p_total = cur.fetchone()['t'] or 0.0
    
    conn.close()
    return {"fiado_hoje": fiado_hoje, "recebido_hoje": recebido_hoje, "total_rua": v_total - p_total}

def fechar_caixa_dia(valor_venda_vista, observacao=""):
    conn = get_connection()
    cur = conn.cursor()
    # No Postgres usamos ON CONFLICT para Upsert (mas precisa de Constraint Unique)
    # Vamos fazer a lógica manual para garantir
    cur.execute("SELECT id FROM caixa_diario WHERE data_referencia = CURRENT_DATE")
    exists = cur.fetchone()
    
    if exists:
        cur.execute("UPDATE caixa_diario SET valor_vendas_vista = %s, observacao = %s WHERE id = %s", 
                    (valor_venda_vista, observacao, exists['id']))
    else:
        cur.execute("INSERT INTO caixa_diario (data_referencia, valor_vendas_vista, observacao) VALUES (CURRENT_DATE, %s, %s)", 
                    (valor_venda_vista, observacao))
    conn.commit()
    conn.close()

def inserir_despesa(descricao, valor, categoria):
    conn = get_connection()
    conn.cursor().execute("INSERT INTO despesas (descricao, valor, categoria, data_despesa) VALUES (%s, %s, %s, CURRENT_DATE)",
                 (descricao, valor, categoria))
    conn.commit()
    conn.close()

def relatorio_mes(mes, ano):
    conn = get_connection()
    cur = conn.cursor()
    # Postgres precisa de cast para data
    start_date = f"{ano}-{mes:02d}-01"
    # Lógica de fim de mês simplificada (fim do mês é < data do proximo mes)
    # Mas vamos usar o between com strings que o postgres aceita bem YYYY-MM-DD
    import calendar
    last_day = calendar.monthrange(ano, mes)[1]
    end_date = f"{ano}-{mes:02d}-{last_day}"

    cur.execute("SELECT SUM(valor_vendas_vista) as t FROM caixa_diario WHERE data_referencia BETWEEN %s AND %s", (start_date, end_date))
    vendas = cur.fetchone()['t'] or 0.0
    
    cur.execute("SELECT SUM(valor) as t FROM pagamentos WHERE DATE(data_pagamento) BETWEEN %s AND %s", (start_date, end_date))
    recebimentos = cur.fetchone()['t'] or 0.0
    
    cur.execute("SELECT SUM(valor) as t FROM despesas WHERE data_despesa BETWEEN %s AND %s", (start_date, end_date))
    despesas = cur.fetchone()['t'] or 0.0
    
    conn.close()
    
    return {
        "entradas_caixa": vendas,
        "recuperado_fiado": recebimentos,
        "total_saidas": despesas,
        "saldo": vendas - despesas
    }

def get_meses_disponiveis():
    conn = get_connection()
    # Extrai mes e ano no Postgres
    query = """
        SELECT EXTRACT(MONTH FROM data_referencia) as mes, EXTRACT(YEAR FROM data_referencia) as ano FROM caixa_diario
        UNION
        SELECT EXTRACT(MONTH FROM data_despesa) as mes, EXTRACT(YEAR FROM data_despesa) as ano FROM despesas
        ORDER BY ano DESC, mes DESC
    """
    resultado = conn.cursor().execute(query) # execute não retorna, fetchall sim
    # Correção para psycopg2
    cur = conn.cursor()
    cur.execute(query)
    rows = cur.fetchall()
    conn.close()
    
    if not rows:
        hoje = datetime.now()
        return [(int(hoje.month), int(hoje.year))]
        
    return [(int(row['mes']), int(row['ano'])) for row in rows]

def get_historico_anual():
    meses = get_meses_disponiveis()
    historico = []
    for mes, ano in meses:
        dados = relatorio_mes(mes, ano)
        historico.append({"mes": mes, "ano": ano, "lucro": dados['saldo']})
    return historico