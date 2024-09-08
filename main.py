from dotenv import load_dotenv
import websocket #NOTE: websocket-client (https://github.com/websocket-client/websocket-client)
import uuid
import json
import urllib.request
import urllib.parse
import requests
import os
from telegram import Update
from telegram.ext import ApplicationBuilder, CallbackQueryHandler, ContextTypes, MessageHandler, filters
import random
from io import BytesIO

client_id = str(uuid.uuid4())

load_dotenv()

server_address = os.getenv('SERVER_ADDRESS', '127.0.0.1:8188')
tg_token = os.getenv('TG_TOKEN', None)
prefix = os.getenv('PREFIX', '!!!')
model = os.getenv('MODEL', 'flux\\flux1-dev.sft')
weight_dtype = os.getenv('WEIGHT_DTYPE', 'fp8_e4m3fn')
t5xxl = os.getenv('T5XXL', 'flux\\t5xxl_fp8_e4m3fn.safetensors')
clip_l = os.getenv('CLIP_L', 'flux\\clip_l.safetensors')
vae_name = os.getenv('VAE', 'flux\\flux_ae.sft')
lora_name = os.getenv('LORA ', 'flux\\flux_dev_NSFW_master.safetensors')
sampler = os.getenv('SAMPLER', 'dpmpp_2m')
scheduler = os.getenv('SCHEDULER', 'sgm_uniform')
cfg_scale = int(os.getenv('CFG_SCALE', 7))
denoising_strength = float(os.getenv('DENOISING_STRENGTH', 0.75))
steps = int(os.getenv('STEPS', 25))
width = int(os.getenv('WIDTH', 512))
height = int(os.getenv('HEIGHT', 512))
batch_size = int(os.getenv('BATCH_SIZE', 1))
send_jpeg = os.getenv('SEND_PHOTO', True ).lower() in ('true')
send_png = os.getenv('SEND_PNG',  True ).lower() in ('true')

def queue_prompt(prompt):
    p = {"prompt": prompt, "client_id": client_id}
    data = json.dumps(p).encode('utf-8')
    req =  urllib.request.Request("http://{}/prompt".format(server_address), data=data)
    return json.loads(urllib.request.urlopen(req).read())

def get_image(filename, subfolder, folder_type):
    data = {"filename": filename, "subfolder": subfolder, "type": folder_type}
    url_values = urllib.parse.urlencode(data)
    with urllib.request.urlopen("http://{}/view?{}".format(server_address, url_values)) as response:
        return response.read()

def get_history(prompt_id):
    with urllib.request.urlopen("http://{}/history/{}".format(server_address, prompt_id)) as response:
        return json.loads(response.read())

def get_images(ws, prompt):
    prompt_id = queue_prompt(prompt)['prompt_id']
    output_images = {}
    while True:
        out = ws.recv()
        if isinstance(out, str):
            message = json.loads(out)
            if message['type'] == 'executing':
                data = message['data']
                if data['node'] is None and data['prompt_id'] == prompt_id:
                    break #Execution is done
        else:
            continue #previews are binary data

    history = get_history(prompt_id)[prompt_id]
    for o in history['outputs']:
        for node_id in history['outputs']:
            node_output = history['outputs'][node_id]
            if 'images' in node_output:
                images_output = []
                for image in node_output['images']:
                    image_data = get_image(image['filename'], image['subfolder'], image['type'])
                    images_output.append(image_data)
            output_images[node_id] = images_output

    return output_images


def upload_file(file, subfolder="", overwrite=False):
    try:
        # Wrap file in formdata so it includes filename
        body = {"image": file}
        data = {}
        
        if overwrite:
            data["overwrite"] = "true"
  
        if subfolder:
            data["subfolder"] = subfolder

        resp = requests.post(f"http://{server_address}/upload/image", files=body,data=data)
        
        if resp.status_code == 200:
            data = resp.json()
            # Add the file to the dropdown list and update the widget value
            path = data["name"]
            if "subfolder" in data:
                if data["subfolder"] != "":
                    path = data["subfolder"] + "/" + path
            

        else:
            print(f"{resp.status_code} - {resp.reason}")
    except Exception as error:
        print(error)
    return path

async def send_message(update: Update, context: ContextTypes.DEFAULT_TYPE, images, delete_chat_id, delete_message_id, send_chat_id, reply_message_id, prompt, image_seed, image_generation_time, option_button_choice='New') -> None:
    if images:
        await context.bot.delete_message(chat_id=delete_chat_id, message_id=delete_message_id)
        for node_id in images:
            for image_data in images[node_id]:
                from PIL import Image
                import io
                image = Image.open(io.BytesIO(image_data))
                if send_jpeg:
                    bio = BytesIO()
                    bio.name = 'image.jpeg'
                    image.save(bio, 'JPEG')
                    bio.seek(0)
                    await context.bot.send_photo(send_chat_id, photo=bio)
                
                if send_png:
                    document = BytesIO()
                    document.name = 'image.png'
                    image.save(document, 'PNG')
                    document.seek(0)
                    await context.bot.send_document(send_chat_id, document)
    elif images is None:
        await context.bot.delete_message(chat_id=delete_chat_id, message_id=delete_message_id)
        await context.bot.send_message(send_chat_id, 'I can\'t reach Stable diffusion right now, come back later \U0001F607')
    else:
        await context.bot.delete_message(chat_id=delete_chat_id, message_id=delete_message_id)
        await context.bot.send_message(send_chat_id, f'Stable Diffusion hit a snag \U0001F62D Here is the error: {image}')
    await context.bot.send_message(send_chat_id, f'{prompt}')

async def txt2img(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message.text.startswith(prefix) or len(update.message.text.split()) < 2:
        return
    txt2img_msg = await update.message.reply_text("Generating...", reply_to_message_id=update.message.message_id)
    txt2img_prompt = update.message.text.replace(prefix,"").replace("\"","\'").strip()
    workflow["6"]["inputs"]["text"]  = f'breathtaking illustration from adult comic book presenting, ultrarealistic, photorealism, high quality texture, {txt2img_prompt}. fabulous artwork. best quality, high resolution'
    seed = random.randint(1, 1000000000)
    workflow["25"]["inputs"]["noise_seed"] = seed
    ws = websocket.WebSocket()
    ws.connect("ws://{}/ws?clientId={}".format(server_address, client_id))
    images = get_images(ws, workflow)
    await send_message(update, context, images, txt2img_msg.chat_id, txt2img_msg.message_id, update.message.chat_id, update.message.message_id, txt2img_prompt, seed, 0)
    
async def options(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    original_message = query.message.reply_to_message
    await query.answer()
    option_prompt = query.message.caption.split('\"')[1::2][0]

#load workflow from file
with open("wf-base.json", "r", encoding="utf-8") as f:
    workflow_data = f.read()

workflow = json.loads(workflow_data)
workflow["10"]["inputs"]["vae_name"] = vae_name
workflow["11"]["inputs"]["clip_name1"] = t5xxl
workflow["11"]["inputs"]["clip_name2"] = clip_l
workflow["12"]["inputs"]["unet_name"] = model
workflow["12"]["inputs"]["weight_dtype"] = weight_dtype
workflow["16"]["inputs"]["sampler_name"] = sampler
workflow["17"]["inputs"]["scheduler"] = scheduler
workflow["17"]["inputs"]["steps"] = steps
workflow["17"]["inputs"]["denoise"] = denoising_strength
#workflow["72"]["inputs"]["lora_name"] = lora_name
workflow["85"]["inputs"]["aspect_ratio"] = 'custom'
workflow["85"]["inputs"]["width"] = width
workflow["85"]["inputs"]["height"] = height
workflow["85"]["inputs"]["batch_size"] = batch_size

if __name__ == '__main__':
    try:
        app = ApplicationBuilder().token(tg_token).build()

        app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND & ~filters.REPLY, txt2img))
        
        app.add_handler(CallbackQueryHandler(options))

        app.run_polling()
    except Exception as e:
        print(e)
