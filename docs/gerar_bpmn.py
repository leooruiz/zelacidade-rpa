"""Gera docs/processo.bpmn (BPMN 2.0 com diagrama) do robô Triagem ZelaCidade."""
import sys
from xml.sax.saxutils import escape

# id: (tipo, rótulo, x, y, w, h, pai)
E = {}
def el(id_, tipo, rotulo, x, y, w=None, h=None, pai="processo"):
    tam = {"start": (36, 36), "end": (36, 36), "gw": (50, 50), "task": (120, 80), "sub": (0, 0)}[tipo]
    E[id_] = dict(tipo=tipo, rotulo=rotulo, x=x, y=y, w=w or tam[0], h=h or tam[1], pai=pai)

Y = 200  # linha central
def cy(id_): return E[id_]["y"] + E[id_]["h"] / 2

el("inicio", "start", "A cada 30 minutos (Agendador do Windows)", 40, Y - 18)
el("ler_config", "task", "Ler .env e regras.json", 120, Y - 40)
el("gw_config", "gw", "Configuração válida?", 290, Y - 25)
el("erro_config", "task", "Registrar ERRO e avisar o responsável por e-mail", 255, Y + 110)
el("fim_config", "end", "Encerra (código 2)", 297, Y + 250)
el("buscar", "task", "Buscar área piloto, recebidas e abertas (até 4 tentativas: 5, 15 e 45 s)", 390, Y - 40, 140)
el("gw_api", "gw", "API respondeu?", 570, Y - 25)
el("erro_api", "task", "Registrar ERRO e e-mail \"API indisponível\"", 535, Y + 110)
el("fim_api", "end", "Encerra (código 3)", 577, Y + 250)
el("chuva", "task", "Consultar chuva prevista para 24 h (Open-Meteo)", 660, Y - 40)

SX, SY, SW, SH = 820, 40, 1000, 330
el("lote", "sub", "Para cada ocorrência recebida (lote, uma por vez)", SX, SY, SW, SH)
P = "lote"
el("ini_item", "start", "", SX + 20, Y - 18, pai=P)
el("validar", "task", "Validar campos e, se for de cidadão, se está na área piloto", SX + 90, Y - 40, pai=P)
el("gw_valida", "gw", "Válida?", SX + 250, Y - 25, pai=P)
el("precisa_info", "task", "Marcar \"precisa de informação\" com o motivo", SX + 215, Y + 75, pai=P)
el("gw_dup", "gw", "Duplicada? (mesma categoria, até 30 m, até 14 dias)", SX + 360, Y - 25, pai=P)
el("duplicada", "task", "Marcar duplicada (+1 confirmação na original)", SX + 325, SY + 25, pai=P)
el("pontuar", "task", "Calcular prioridade por pontos e escrever o motivo", SX + 470, Y - 40, pai=P)
el("gw_junta", "gw", "", SX + 630, Y - 25, pai=P)
el("patch", "task", "Enviar triagem ao MVP (falha no item: registra e segue)", SX + 715, Y - 40, pai=P)
el("avisar", "task", "E-mail ao gestor se alta e ao morador se consentiu", SX + 715, Y + 75, pai=P)
el("fim_item", "end", "", SX + 940, Y + 97, pai=P)

X2 = SX + SW + 50
el("procurar", "task", "Procurar o ouro_painel_*.json mais recente em entrada/ouro", X2, Y - 40)
el("gw_painel", "gw", "Arquivo do painel?", X2 + 170, Y - 25)
el("rejeitar", "task", "Mover para rejeitados/ e avisar o responsável", X2 + 135, Y + 110)
el("publicar", "task", "Publicar indicadores no MVP", X2 + 270, Y - 40)
el("gw_fim", "gw", "", X2 + 430, Y - 25)
el("fechar", "task", "Gravar log JSONL e relatório CSV; e-mail de resumo", X2 + 520, Y - 40, 130)
el("fim", "end", "Fim (código 0, ou 1 se houve falha em item)", X2 + 700, Y - 18)

# fluxos: (id, origem, destino, rótulo, pontos) — pontos None = reta entre bordas
F = []
def fl(o, d, rotulo="", pontos=None):
    F.append((f"f_{o}_{d}", o, d, rotulo, pontos))

def dir_(id_): e = E[id_]; return (e["x"] + e["w"], cy(id_))
def esq(id_): e = E[id_]; return (e["x"], cy(id_))
def baixo(id_): e = E[id_]; return (e["x"] + e["w"] / 2, e["y"] + e["h"])
def cima(id_): e = E[id_]; return (e["x"] + e["w"] / 2, e["y"])

fl("inicio", "ler_config")
fl("ler_config", "gw_config")
fl("gw_config", "buscar", "Sim")
fl("gw_config", "erro_config", "Não", [baixo("gw_config"), cima("erro_config")])
fl("erro_config", "fim_config", "", [baixo("erro_config"), cima("fim_config")])
fl("buscar", "gw_api")
fl("gw_api", "chuva", "Sim")
fl("gw_api", "erro_api", "Não", [baixo("gw_api"), cima("erro_api")])
fl("erro_api", "fim_api", "", [baixo("erro_api"), cima("fim_api")])
fl("chuva", "lote", "", [dir_("chuva"), (SX, Y)])
fl("ini_item", "validar")
fl("validar", "gw_valida")
fl("gw_valida", "gw_dup", "Sim")
fl("gw_valida", "precisa_info", "Não", [baixo("gw_valida"), cima("precisa_info")])
fl("gw_dup", "duplicada", "Sim", [cima("gw_dup"), baixo("duplicada")])
fl("gw_dup", "pontuar", "Não")
fl("pontuar", "gw_junta")
fl("duplicada", "gw_junta", "", [dir_("duplicada"), (E["gw_junta"]["x"] + 25, cy("duplicada")), cima("gw_junta")])
fl("precisa_info", "gw_junta", "", [dir_("precisa_info"), (E["gw_junta"]["x"] + 25, cy("precisa_info")), baixo("gw_junta")])
fl("gw_junta", "patch")
fl("patch", "avisar", "", [baixo("patch"), cima("avisar")])
fl("avisar", "fim_item")
fl("lote", "procurar", "", [(SX + SW, Y), esq("procurar")])
fl("procurar", "gw_painel")
fl("gw_painel", "publicar", "Válido")
fl("gw_painel", "rejeitar", "Inválido", [baixo("gw_painel"), cima("rejeitar")])
fl("gw_painel", "gw_fim", "Ausente: mantém o painel atual",
   [cima("gw_painel"), (E["gw_painel"]["x"] + 25, Y - 90), (E["gw_fim"]["x"] + 25, Y - 90), cima("gw_fim")])
fl("publicar", "gw_fim")
fl("rejeitar", "gw_fim", "", [dir_("rejeitar"), (E["gw_fim"]["x"] + 25, cy("rejeitar")), baixo("gw_fim")])
fl("gw_fim", "fechar")
fl("fechar", "fim")

TAG = {"start": "startEvent", "end": "endEvent", "gw": "exclusiveGateway", "task": "task", "sub": "subProcess"}


def no_xml(id_, filhos=""):
    e = E[id_]
    entra = "".join(f"<bpmn:incoming>{f[0]}</bpmn:incoming>" for f in F if f[2] == id_)
    sai = "".join(f"<bpmn:outgoing>{f[0]}</bpmn:outgoing>" for f in F if f[1] == id_)
    extra = ""
    if id_ == "inicio":
        extra = '<bpmn:timerEventDefinition id="timer_30min"><bpmn:timeCycle xsi:type="bpmn:tFormalExpression">R/PT30M</bpmn:timeCycle></bpmn:timerEventDefinition>'
    if e["tipo"] == "sub":
        extra = '<bpmn:multiInstanceLoopCharacteristics isSequential="true" />'
    nome = f' name="{escape(e["rotulo"], {chr(34): "&quot;"})}"' if e["rotulo"] else ""
    return f'<bpmn:{TAG[e["tipo"]]} id="{id_}"{nome}>{entra}{sai}{extra}{filhos}</bpmn:{TAG[e["tipo"]]}>'


def fluxo_xml(f):
    nome = f' name="{escape(f[3])}"' if f[3] else ""
    return f'<bpmn:sequenceFlow id="{f[0]}"{nome} sourceRef="{f[1]}" targetRef="{f[2]}" />'


dentro = [k for k, v in E.items() if v["pai"] == "lote"]
fora = [k for k, v in E.items() if v["pai"] == "processo"]
filhos_lote = "".join(no_xml(k) for k in dentro) + "".join(fluxo_xml(f) for f in F if f[1] in dentro)
processo = "".join(no_xml(k, filhos_lote if k == "lote" else "") for k in fora)
processo += "".join(fluxo_xml(f) for f in F if f[1] not in dentro)

formas = []
for k, e in E.items():
    expandido = ' isExpanded="true"' if e["tipo"] == "sub" else ""
    marcador = ' isMarkerVisible="true"' if e["tipo"] == "gw" else ""
    rotulo = ""
    if e["tipo"] in ("start", "end", "gw") and e["rotulo"]:
        lx, ly = e["x"] - 30, e["y"] + e["h"] + 6
        if e["tipo"] == "gw":
            lx, ly = e["x"] - 40, e["y"] - 40
        if k == "gw_painel":
            lx, ly = e["x"] - 125, e["y"] - 52
        if k == "gw_dup":
            lx, ly = e["x"] - 5, e["y"] + 56
        rotulo = f'<bpmndi:BPMNLabel><dc:Bounds x="{lx}" y="{ly}" width="{e["w"] + 60 if e["tipo"] != "gw" else 130}" height="30" /></bpmndi:BPMNLabel>'
    formas.append(f'<bpmndi:BPMNShape id="{k}_di" bpmnElement="{k}"{expandido}{marcador}>'
                  f'<dc:Bounds x="{e["x"]}" y="{e["y"]}" width="{e["w"]}" height="{e["h"]}" />{rotulo}</bpmndi:BPMNShape>')
for id_, o, d, rotulo, pontos in F:
    if pontos is None:
        pontos = [dir_(o), esq(d)]
    wps = "".join(f'<di:waypoint x="{x:.0f}" y="{y:.0f}" />' for x, y in pontos)
    lbl = ""
    if rotulo:
        x0, y0 = pontos[0]
        largura = max(30, len(rotulo) * 6)
        lx, ly = x0 + 6, y0 - 20
        if pontos[1][0] == x0 and pontos[1][1] > y0:  # sai para baixo
            lx, ly = x0 + 6, y0 + 8
        if pontos[1][0] == x0 and pontos[1][1] < y0 and len(pontos) > 2:  # sai para cima e contorna
            lx, ly = pontos[1][0] + 30, pontos[1][1] - 18
        lbl = f'<bpmndi:BPMNLabel><dc:Bounds x="{lx:.0f}" y="{ly:.0f}" width="{largura}" height="14" /></bpmndi:BPMNLabel>'
    formas.append(f'<bpmndi:BPMNEdge id="{id_}_di" bpmnElement="{id_}">{wps}{lbl}</bpmndi:BPMNEdge>')

xml = f'''<?xml version="1.0" encoding="UTF-8"?>
<bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL" xmlns:bpmndi="http://www.omg.org/spec/BPMN/20100524/DI" xmlns:dc="http://www.omg.org/spec/DD/20100524/DC" xmlns:di="http://www.omg.org/spec/DD/20100524/DI" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" id="definicoes_triagem" targetNamespace="https://github.com/leooruiz/zelacidade-rpa" exporter="gerado à mão para o ZelaCidade" exporterVersion="1.0">
<bpmn:process id="processo" name="Triagem ZelaCidade" isExecutable="false">{processo}</bpmn:process>
<bpmndi:BPMNDiagram id="diagrama"><bpmndi:BPMNPlane id="plano" bpmnElement="processo">{"".join(formas)}</bpmndi:BPMNPlane></bpmndi:BPMNDiagram>
</bpmn:definitions>
'''
open(sys.argv[1], "w", encoding="utf-8").write(xml)
print("ok", len(E), "elementos", len(F), "fluxos")
