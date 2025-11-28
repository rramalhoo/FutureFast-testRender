from flask import Flask, request, jsonify, send_file, render_template
from flask_cors import CORS
from openai import OpenAI
import os
import uuid
import base64
from urllib.parse import unquote
import io # Importe o 'io' se não estiver lá, embora 'read()' deva funcionar sem ele

# Supondo que 'config.py' está na mesma pasta e tem as chaves
import os # Adicione 'os' no topo do seu arquivo

try:
    OPENAI_API_KEY = os.environ.get('OPENAI_API_KEY')
    OPENAI_ORGANIZATION = os.environ.get('OPENAI_ORGANIZATION')
    
    if not OPENAI_API_KEY or not OPENAI_ORGANIZATION:
        print("ERRO: Variáveis de ambiente OPENAI_API_KEY ou OPENAI_ORGANIZATION não configuradas.")
        client = None
    else:
        client = OpenAI(
            api_key=OPENAI_API_KEY,
            organization=OPENAI_ORGANIZATION
        )
except Exception as e:
    print(f"Erro ao iniciar cliente OpenAI: {e}")
    client = None

app = Flask(__name__, static_folder='static', static_url_path='/static')
CORS(app)

# --- Rotas das Páginas HTML ---

@app.route("/")
@app.route("/index.html")
def index():
    """Página inicial"""
    return send_file('index.html')

@app.route("/sobre.html")
def sobre():
    """Página do sobre"""
    return send_file('sobre.html')

@app.route("/digitar.html")
def digitar():
    """Página para digitar o problema"""
    return send_file('digitar.html')

@app.route("/falar.html")
def falar():
    """Página para falar o problema"""
    return send_file('falar.html')

@app.route("/resultadoTextoIa.html")
def resultado_texto():
    """Página de resultado (Texto + Imagem)"""
    return send_file('resultadoTextoIa.html')

@app.route("/resultadoAudioIa.html")
@app.route("/resultadoFalaIa.html") # Adicionando rota que deu 404
def resultado_audio():
    """Página de resultado (Áudio + Imagem)"""
    return send_file('resultadoAudioIa.html')

# --- Rotas da API (que geram conteúdo) ---

@app.route("/gerar_solucao_e_imagem", methods=["POST"])
def gerar_solucao_e_imagem():
    """Gera uma solução em texto E uma imagem, via texto."""
    if not client:
        return jsonify({"erro": "Configuração da API da OpenAI não encontrada no servidor."}), 500
        
    data = request.json
    problema = data.get("problema")
    nome = data.get("nome", "Visitante") # Pega o nome, com um padrão

    print(f"Novo pedido de texto de: {nome}")
    print(f"Problema: {problema}")

    if not problema:
        return jsonify({"erro": "Por favor, descreva seu problema."}), 400

    try:
        # --- 1. Filtro de Tema ---
        print("Verificando tema...")
        verificacao = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "Você é um classificador de tópicos. Responda apenas 'sim' ou 'não'. O tópico é sobre o oceano, mar, vida marinha, poluição marinha ou ecossistemas aquáticos?"},
                {"role": "user", "content": problema}
            ],
            max_tokens=2
        )
        tema = verificacao.choices[0].message.content.lower()

        if "não" in tema:
            print("Tema REJEITADO.")
            return jsonify({"erro": "Desculpe, só posso conversar sobre problemas relacionados ao mar..."}), 400
        
        print("Tema ACEITO.")

        # --- 2. Gerar Solução em Texto ---
        print("Gerando solução em texto...")
        solucao_resposta = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "Você é um assistente especializado em ecologia marinha. Dê soluções concisas e diretas (máx 100 palavras) para problemas do oceano."},
                {"role": "user", "content": f"Meu nome é {nome}. Meu problema é: {problema}. Qual é uma boa solução?"}
            ]
        )
        texto_solucao = solucao_resposta.choices[0].message.content
        print(f"Solução: {texto_solucao}")

        # --- 3. Gerar Prompt de Imagem ---
        print("Gerando prompt de imagem...")
        prompt_resposta = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "Você é um especialista em prompts para DALL-E. Crie um prompt curto (máx 20 palavras) para uma imagem fotorrealista que ilustre a SOLUÇÃO, não o problema. Foco na ação positiva."},
                {"role": "user", "content": f"Problema: {problema}\nSolução: {texto_solucao}"}
            ]
        )
        prompt_enriquecido = prompt_resposta.choices[0].message.content
        print(f"Prompt de Imagem: {prompt_enriquecido}")

        # --- 4. Gerar Imagem ---
        print("Gerando imagem com DALL-E 3...")
        imagem = client.images.generate(
            model="dall-e-3",
            prompt=f"Photorealistic, high quality: {prompt_enriquecido}",
            size="1024x1024",
            response_format="b64_json"
        )
        b64_imagem = imagem.data[0].b64_json
        
        # Salvar imagem localmente (Opcional, mas bom para debug)
        if not os.path.exists('imagens'):
            os.makedirs('imagens')
        filename = f"{uuid.uuid4()}.png"
        filepath = os.path.join("imagens", filename)
        with open(filepath, "wb") as f:
            f.write(base64.b64decode(b64_imagem))
        print(f"Imagem salva em: {filepath}")

        local_url = f"/imagem/{filename}"

        return jsonify({
            "texto_solucao": texto_solucao,
            "imagem_url": local_url
        })

    except Exception as e:
        print(f"ERRO GERAL NA API DE TEXTO: {str(e)}")
        return jsonify({"erro": f"Erro ao gerar conteúdo: {str(e)}"}), 500

@app.route("/gerar_solucao_audio", methods=["POST"])
def gerar_solucao_audio():
    """Gera uma solução em ÁUDIO E uma imagem, via áudio."""
    if not client:
        return jsonify({"erro": "Configuração da API da OpenAI não encontrada no servidor."}), 500

    try:
        nome = request.form.get("nome", "Visitante")
        
        if 'audio_data' not in request.files:
            return jsonify({"erro": "Nenhum arquivo de áudio enviado."}), 400

        audio_file = request.files['audio_data']
        print(f"\nNovo pedido de áudio de: {nome}")

        # --- 1. Transcrever Áudio (Whisper) ---
        print("Transcrevendo áudio com Whisper...")

        # ################################################
        # AQUI ESTÁ A CORREÇÃO
        # Nós passamos uma tupla (nome_do_arquivo, dados_em_bytes)
        # ################################################
        transcricao = client.audio.transcriptions.create(
            model="whisper-1",
            file=(audio_file.filename, audio_file.read()),
            language="pt"
        )
        problema_texto = transcricao.text
        print(f"Texto transcrito: {problema_texto}")

        # --- 2. Filtro de Tema ---
        print("Verificando tema...")
        verificacao = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "Você é um classificador de tópicos. Responda apenas 'sim' ou 'não'. O tópico é sobre o oceano, mar, vida marinha, poluição marinha ou ecossistemas aquáticos?"},
                {"role": "user", "content": problema_texto}
            ],
            max_tokens=2
        )
        tema = verificacao.choices[0].message.content.lower()

        if "não" in tema:
            print("Tema REJEITADO.")
            return jsonify({"erro": "Desculpe, só posso falar sobre problemas do mar..."}), 400
        
        print("Tema ACEITO.")
        
        # --- 3. Gerar Solução em Texto ---
        print("Gerando solução em texto...")
        solucao_resposta = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "Você é um assistente especializado em ecologia marinha. Dê soluções concisas e diretas (máx 100 palavras) para problemas do oceano."},
                {"role": "user", "content": f"Meu nome é {nome}. Meu problema é: {problema_texto}. Qual é uma boa solução?"}
            ]
        )
        texto_solucao = solucao_resposta.choices[0].message.content
        print(f"Solução: {texto_solucao}")

        # --- 4. Gerar Prompt de Imagem ---
        print("Gerando prompt de imagem...")
        prompt_resposta = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "Você é um especialista em prompts para DALL-E. Crie um prompt curto (máx 20 palavras) para uma imagem fotorrealista que ilustre a SOLUÇÃO, não o problema. Foco na ação positiva."},
                {"role": "user", "content": f"Problema: {problema_texto}\nSolução: {texto_solucao}"}
            ]
        )
        prompt_enriquecido = prompt_resposta.choices[0].message.content
        print(f"Prompt de Imagem: {prompt_enriquecido}")

        # --- 5. Gerar Imagem (DALL-E) ---
        print("Gerando imagem com DALL-E 3...")
        imagem = client.images.generate(
            model="dall-e-3",
            prompt=f"Photorealistic, high quality: {prompt_enriquecido}",
            size="1024x1024",
            response_format="b64_json"
        )
        b64_imagem = imagem.data[0].b64_json

        # Salvar imagem
        if not os.path.exists('imagens'):
            os.makedirs('imagens')
        img_filename = f"{uuid.uuid4()}.png"
        img_filepath = os.path.join("imagens", img_filename)
        with open(img_filepath, "wb") as f:
            f.write(base64.b64decode(b64_imagem))
        img_local_url = f"/{img_filename}"
        print(f"Imagem salva em: {img_filepath}")

        # --- 6. Gerar Áudio da Solução (TTS) ---
        print("Gerando áudio da solução (TTS)...")
        if not os.path.exists('audios'):
            os.makedirs('audios')
        
        audio_filename = f"solucao_{uuid.uuid4()}.mp3"
        audio_filepath = os.path.join("audios", audio_filename)
        
        resposta_audio = client.audio.speech.create(
            model="tts-1",
            voice="alloy",
            input=texto_solucao
        )
        
        # Salva o áudio no arquivo
        resposta_audio.stream_to_file(audio_filepath)
        print(f"Áudio da solução salvo em: {audio_filepath}")
        
        audio_local_url = f"/{audio_filename}"

        return jsonify({
            "audio_url": audio_local_url,
            "imagem_url": img_local_url
        })

    except Exception as e:
        print(f"ERRO GERAL NA API DE AUDIO: {str(e)}")
        # Isso irá printar o traceback completo no console para debug
        import traceback
        traceback.print_exc()
        return jsonify({"erro": f"Erro no servidor ao processar áudio: {str(e)}"}), 500


# --- Rotas de Servir Arquivos (Imagens/Áudio) ---

@app.route("/imagem/<filename>")
def servir_imagem(filename):
    """Servir imagem local da pasta 'imagens'"""
    try:
        return send_file(f'imagens/{filename}')
    except Exception as e:
        return f"Erro ao carregar imagem: {str(e)}", 404

@app.route("/audio/<filename>")
def servir_audio(filename):
    """Servir áudio local da pasta 'audios'"""
    try:
        return send_file(f'audios/{filename}')
    except Exception as e:
        return f"Erro ao carregar áudio: {str(e)}", 404

# --- Ponto de Entrada ---
if __name__ == "__main__":
    app.run(debug=True, host='127.0.0.1', port=5000)