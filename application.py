from flask import Flask, request, jsonify
import requests
import json
import re
from datetime import datetime, timedelta
import os
import smtplib
import ssl
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

# Importaciones para Google Calendar API
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

# Importaciones para iCalendar (.ics)
from icalendar import Calendar, Event as IcsEvent
import tempfile
import os

# Crear la aplicación Flask (cambiar 'app' por 'application' para Passenger)
application = Flask(__name__)

# === CONFIGURACIÓN ===
META_ACCESS_TOKEN = os.environ.get('META_ACCESS_TOKEN') or 'temporal_token_placeholder'
META_PHONE_NUMBER_ID = os.environ.get('META_PHONE_NUMBER_ID') or '123456789012345'
META_VERIFY_TOKEN = os.environ.get('META_VERIFY_TOKEN') or 'milkiin_verify_token_2024'

# Variables para Google Calendar
GOOGLE_CALENDAR_CREDENTIALS_JSON = os.environ.get('GOOGLE_CALENDAR_CREDENTIALS')
GOOGLE_CALENDAR_ID = os.environ.get('GOOGLE_CALENDAR_ID')
SCOPES = ['https://www.googleapis.com/auth/calendar.events']

# === CONFIGURACIÓN DE CORREO ELECTRÓNICO ===
EMAIL_ADDRESS = os.environ.get('EMAIL_ADDRESS')
EMAIL_PASSWORD = os.environ.get('EMAIL_PASSWORD')
SMTP_SERVER = 'smtp.gmail.com'
SMTP_PORT = 465

# === TOKEN DE SEGURIDAD PARA RECORDATORIOS (opcional) ===
REMINDER_TOKEN = os.environ.get('REMINDER_TOKEN')

# === AUTENTICACIÓN Y SERVICIO DE CALENDAR ===
def get_calendar_service():
    try:
        info = json.loads(GOOGLE_CALENDAR_CREDENTIALS_JSON)
        credentials = service_account.Credentials.from_service_account_info(
            info,
            scopes=SCOPES
        )
        service = build('calendar', 'v3', credentials=credentials)
        return service
    except (json.JSONDecodeError, HttpError) as e:
        print(f"❌ Error al inicializar el servicio de Google Calendar: {e}")
        return None

# === ESTADO DE CONVERSACIÓN ===
user_state = {}
user_data_storage = {}

# === MENSAJES DEL BOT (ACTUALIZADO) ===
WELCOME_MESSAGE = {
    "type": "text",
    "text": {
        "body": "Bienvenido(a) a Milkiin.\nEstamos aquí para brindarte la mejor atención.\n\nSelecciona la opción que corresponda a tu necesidad:\n1- Paciente de primera vez\n2- Paciente subsecuente\n3- Atención al cliente\n4- Facturación\n5- Envío de resultados\n6- Dudas, preguntas y cancelaciones\n\nPor favor, responde con el número de la opción que elijas."
    }
}

SERVICIOS_PRIMERA_VEZ = {
    "type": "text",
    "text": {
        "body": ("Selecciona el servicio de primera vez:\n"
                 "1️⃣ Fertilidad\n"
                 "2️⃣ Síndrome de Ovario Poliquístico\n"
                 "3️⃣ Chequeo Anual\n"
                 "4️⃣ Embarazo\n"
                 "5️⃣ Ginecología Pediátrica y Adolescentes\n"
                 "6️⃣ Revisión de Estudios\n"
                 "7️⃣ Agendar Espermatobioscopia con América")
    }
}

SERVICIOS_SUBSECUENTE = {
    "type": "text",
    "text": {
        "body": "Selecciona el servicio subsecuente:\n1️⃣ Fertilidad\n2️⃣ Síndrome de Ovario Poliquístico\n3️⃣ Chequeo Anual\n4️⃣ Embarazo\n5️⃣ Revisión de estudios\n6️⃣ Seguimiento folicular\n7️⃣ Otros"
    }
}

OTROS_OPCIONES = {
    "type": "text",
    "text": {
        "body": "Selecciona una opción:\n1️⃣ Espermabiopsia directa\n2️⃣ Ginecología Pediátrica y Adolescentes\n3️⃣ Hablar con América"
    }
}

# === MAPEOS Y LÓGICA DE ESPECIALISTAS (ACTUALIZADO) ===
ESPECIALISTAS_NOMBRES = {
    "1": "Dra. Mónica Olavarría",
    "2": "Dra. Graciela Guadarrama",
    "3": "Dra. Cinthia Ruiz",
    "4": "Dra. Gisela Cuevas",
    "5": "Dra. Gabriela Sánchez"
}

ESPECIALISTAS_POR_SERVICIO = {
    "1": ["1", "4"],
    "2": ["1", "3", "4"],
    "3": ["1", "2", "3", "4", "5"],
    "4": ["1", "2", "3", "4", "5"],
    "5": ["3"],
    "6": ["1", "2", "3", "4", "5"]
}

def get_specialist_menu(service_key):
    especialistas_disponibles = ESPECIALISTAS_POR_SERVICIO.get(service_key, [])
    if not especialistas_disponibles:
        return None
    menu_text = "Selecciona tu especialista:\n"
    for key in especialistas_disponibles:
        menu_text += f"▪️ {key}: {ESPECIALISTAS_NOMBRES[key]}\n"
    return {
        "type": "text",
        "text": {"body": menu_text}
    }

SERVICIOS_NOMBRES = {
    "1": "Fertilidad",
    "2": "Síndrome de Ovario Poliquístico",
    "3": "Chequeo Anual",
    "4": "Embarazo",
    "5": "Ginecología Pediátrica y Adolescentes",
    "6": "Revisión de Estudios",
    "7": "Espermatobioscopia"
}

SERVICIOS_SUB_NOMBRES = {
    "1": "Fertilidad",
    "2": "Síndrome de Ovario Poliquístico",
    "3": "Chequeo Anual",
    "4": "Embarazo",
    "5": "Revisión de estudios",
    "6": "Seguimiento folicular",
    "7": "Otros"
}

# CORRECCIÓN: Duraciones de cita para primera vez según el PDF
DURACIONES_PRIMERA_VEZ = {
    "1": 30, # Fertilidad - 30 minutos
    "2": 60, # Síndrome de Ovario Poliquístico - 60 minutos
    "3": 60, # Chequeo Anual - 60 minutos
    "4": 60, # Embarazo - 60 minutos
    "5": 60, # Ginecología Pediátrica y Adolescentes - 60 minutos
    "6": 30  # Revisión de Estudios - 30 minutos
}

# CORRECCIÓN: Duraciones de cita para subsecuente según el PDF
DURACIONES_SUBSECUENTE = {
    "1": 30, # Fertilidad - 30 minutos
    "2": 45, # Síndrome de Ovario Poliquístico - 45 minutos
    "3": 45, # Chequeo Anual - 45 minutos
    "4": 45, # Embarazo - 45 minutos
    "5": 30, # Revisión de estudios - 30 minutos
    "6": 30, # Seguimiento folicular - 30 minutos
    "7": 30  # Otros - 30 minutos
}

COSTOS = {
    "type": "text",
    "text": {
        "body": "💰 Nuestros costos:\n\n• PAQUETE CHECK UP: $1,800 pesos (incluye papanicolaou, USG , revisión de mamas, colposcopia y consulta)\n• CONSULTA DE FERTILIDAD: $1,500 pesos. (incluye ultrasonido)\n• CONSULTA PRENATAL: $1,500 pesos. (incluye ultrasonido)\n• ESPERMABIOTOSCOPIA: $1,500 pesos\n• ESPERMABIOTOSCOPIA CON FRAGMENTACIÓN: $4,500 pesos"
    }
}

CONFIRMACION = {
    "type": "text",
    "text": {
        "body": ("✅ ¡Gracias por agendar tu cita con Milkiin!\n\n"
                 "Te esperamos en: Insurgentes Sur 1160, 6º piso, Colonia Del Valle.\n"
                 "🗺️ Ubicación en Google Maps: https://maps.app.goo.gl/c2nUy7HwAM8jhANe8\n"
                 "💳 Aceptamos pagos con tarjeta (incluyendo AMEX) y en efectivo.\n\n"
                 "❗️ En caso de cancelación, es necesario avisar con mínimo 72 horas de anticipación para poder realizar el reembolso del anticipo y reprogramar tu cita. Si no se cumple con este plazo, lamentablemente no podremos hacer el reembolso.\n\n"
                 "Agradecemos tu comprensión y tu confianza. Estamos para acompañarte con profesionalismo y cariño en cada paso. ❤️\n\n"
                 "Si tienes alguna duda o necesitas apoyo adicional, no dudes en escribirnos. ¡Será un gusto atenderte!")
    }
}

# === FUNCIONES PARA WHATSAPP META API ===
def send_whatsapp_message(phone_number, message_data):
    try:
        url = f"https://graph.facebook.com/v22.0/{META_PHONE_NUMBER_ID}/messages"
        headers = {
            'Authorization': f'Bearer {META_ACCESS_TOKEN}',
            'Content-Type': 'application/json'
        }
        formatted_phone = format_phone_number(phone_number)
        payload = {
            "messaging_product": "whatsapp",
            "to": formatted_phone,
            "type": message_data["type"]
        }
        if message_data["type"] == "text":
            payload["text"] = message_data["text"]
        elif message_data["type"] == "template":
            payload["template"] = message_data["template"]
        response = requests.post(url, headers=headers, json=payload)
        if response.status_code == 200:
            print(f"✅ Mensaje enviado a {phone_number}")
            return response.json()
        else:
            print(f"❌ Error enviando mensaje: {response.status_code} - {response.text}")
            return None
    except Exception as e:
        print(f"❌ Error en send_whatsapp_message: {e}")
        return None

def format_phone_number(phone):
    clean_phone = re.sub(r'\D', '', phone)
    if clean_phone.startswith('52') and len(clean_phone) == 12:
        return clean_phone
    elif clean_phone.startswith('1') and len(clean_phone) == 11:
        return '52' + clean_phone[1:]
    elif len(clean_phone) == 10:
        return '52' + clean_phone
    return clean_phone

def extract_user_data(message_body):
    data = {}
    lines = message_body.split('\n')
    for line in lines:
        if 'nombre' in line.lower() or 'paciente' in line.lower():
            data['nombre'] = line.split(':', 1)[1].strip() if ':' in line else line
        elif re.search(r'\d{10,}', line):
            phone_match = re.search(r'\d{10,}', line)
            if phone_match:
                data['telefono'] = phone_match.group(0)
    return data

# === GENERAR ARCHIVO .ICS ===
def generar_archivo_ics(nombre_paciente, servicio, especialista, fecha_hora, duracion_minutos):
    cal = Calendar()
    event = IcsEvent()
    event.add('summary', f"Cita en Milkiin - {servicio}")
    event.add('dtstart', fecha_hora)
    event.add('dtend', fecha_hora + timedelta(minutes=duracion_minutos))
    event.add('location', "Insurgentes Sur 1160, 6º piso, Colonia Del Valle, Ciudad de México")
    event.add('description', f"""
Cita agendada con éxito en Milkiin ❤️

Servicio: {servicio}
Especialista: {especialista}
Paciente: {nombre_paciente}

📍 Dirección: Insurgentes Sur 1160, 6º piso, Colonia Del Valle
🗺️ [Google Maps](https://maps.app.goo.gl/c2nUy7HwAM8jhANe8)

💳 Aceptamos tarjeta (incluyendo AMEX) y efectivo.
⏰ Recordatorio: Si necesitas cancelar, avísanos con 72 horas de anticipación.

¡Te esperamos con cariño!
    """.strip())
    cal.add_component(event)
    temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=".ics")
    temp_file.write(cal.to_ical())
    temp_file.close()
    return temp_file.name

# === GOOGLE CALENDAR ===
def crear_evento_google_calendar(resumen, inicio, duracion_minutos, descripcion):
    try:
        service = get_calendar_service()
        if not service:
            return None
        fin = inicio + timedelta(minutes=duracion_minutos)
        event = {
            'summary': resumen,
            'description': descripcion,
            'start': {
                'dateTime': inicio.isoformat(),
                'timeZone': 'America/Mexico_City',
            },
            'end': {
                'dateTime': fin.isoformat(),
                'timeZone': 'America/Mexico_City',
            },
        }
        event = service.events().insert(calendarId=GOOGLE_CALENDAR_ID, body=event).execute()
        print(f"✅ Evento de Google Calendar creado: {event.get('htmlLink')}")
        return event.get('htmlLink')
    except HttpError as error:
        print(f"❌ Error al crear evento de Google Calendar: {error}")
        return None
    except Exception as e:
        print(f"❌ Error desconocido: {e}")
        return None

# === ENVÍO DE CORREO ===
def send_appointment_email(recipient_email, clinic_email, service_name, patient_name, patient_phone, patient_dob, patient_age, doctor_name, appointment_date, appointment_time):
    if not all([EMAIL_ADDRESS, EMAIL_PASSWORD]):
        print("❌ Error: Faltan credenciales de correo.")
        return False
    
    if recipient_email:
        message_patient = MIMEMultipart("alternative")
        message_patient["Subject"] = "Confirmación de Cita - Milkiin"
        message_patient["From"] = EMAIL_ADDRESS
        message_patient["To"] = recipient_email
        html_patient = f"""
        <html><body>
        <p>Hola <strong>{patient_name}</strong>,</p>
        <p>Tu cita con <strong>{doctor_name}</strong> ha sido agendada con éxito.</p>
        <p>Detalles:</p>
        <ul>
            <li><strong>Fecha:</strong> {appointment_date}</li>
            <li><strong>Hora:</strong> {appointment_time}</li>
        </ul>
        </body></html>
        """
        message_patient.attach(MIMEText(html_patient, "html"))
    
    message_clinic = MIMEMultipart("alternative")
    message_clinic["Subject"] = "NUEVA CITA AGENDADA"
    message_clinic["From"] = EMAIL_ADDRESS
    message_clinic["To"] = clinic_email
    text_clinic = f"""
    ¡Nueva cita agendada!
    Servicio: {service_name}
    Fecha: {appointment_date} a las {appointment_time}
    Paciente: {patient_name}
    Teléfono: {patient_phone}
    Fecha de Nacimiento: {patient_dob}
    Edad: {patient_age} años
    """
    message_clinic.attach(MIMEText(text_clinic, "plain"))
    
    context = ssl.create_default_context()
    try:
        with smtplib.SMTP_SSL(SMTP_SERVER, SMTP_PORT, context=context) as server:
            server.login(EMAIL_ADDRESS, EMAIL_PASSWORD)
            if recipient_email:
                server.sendmail(EMAIL_ADDRESS, recipient_email, message_patient.as_string())
                print(f"✅ Correo de confirmación enviado a {recipient_email}")
            server.sendmail(EMAIL_ADDRESS, clinic_email, message_clinic.as_string())
            print(f"✅ Correo de notificación enviado a la clínica a {clinic_email}")
            return True
    except Exception as e:
        print(f"❌ Error al enviar correo: {e}")
        return False

# === PROCESAMIENTO DE MENSAJES ===
def process_user_message(phone_number, message_body):
    user_data = user_state.get(phone_number, {"stage": "start"})
    user_info = user_data_storage.get(phone_number, {})
    print(f"[MENSAJE ENTRANTE] {phone_number}: {message_body}")

    if message_body.lower() == "hola" and user_data["stage"] != "start":
        user_data["stage"] = "start"
    
    if user_data["stage"] == "start":
        send_whatsapp_message(phone_number, WELCOME_MESSAGE)
        user_data["stage"] = "option_selected"

    elif user_data["stage"] == "option_selected":
        if message_body == "1":
            user_data["tipo"] = "primera_vez"
            user_data["stage"] = "servicio_primera"
            send_whatsapp_message(phone_number, SERVICIOS_PRIMERA_VEZ)
        elif message_body == "2":
            user_data["tipo"] = "subsecuente"
            user_data["stage"] = "servicio_subsecuente"
            send_whatsapp_message(phone_number, SERVICIOS_SUBSECUENTE)
        elif message_body == "3":
            user_data["stage"] = "atencion_cliente"
            send_whatsapp_message(phone_number, {"type": "text", "text": {"body": "1️⃣ COSTOS\n2️⃣ Hablar con América"}})
        elif message_body == "4":
            user_data["stage"] = "facturacion"
            send_whatsapp_message(phone_number, {"type": "text", "text": {"body": "1️⃣ Requiero factura\n2️⃣ Dudas"}})
        elif message_body == "5":
            send_whatsapp_message(phone_number, {"type": "text", "text": {"body": "Para el envío de resultados, envíalos al correo:\n📧 nicontacto@heyginemoni.com"}})
            user_data["stage"] = "start"
        elif message_body == "6":
            send_whatsapp_message(phone_number, {"type": "text", "text": {"body": "Para dudas o cancelaciones, puedes escribirnos a:\n📧 contacto@heyginemoni.com"}})
            user_data["stage"] = "start"
        else:
            send_whatsapp_message(phone_number, {"type": "text", "text": {"body": "Por favor, selecciona una opción válida del 1 al 6."}})

    # === PRIMERA VEZ (FLUJO ACTUALIZADO) ===
    elif user_data["stage"] == "servicio_primera":
        if message_body == "7":
            send_whatsapp_message(phone_number, {"type": "text", "text": {"body": "Claro, en un momento uno de nuestros asesores te atenderá para agendar tu cita de Espermatobioscopia. Gracias por tu paciencia."}})
            if phone_number in user_state: del user_state[phone_number]
            if phone_number in user_data_storage: del user_data_storage[phone_number]
        elif message_body in ["1", "2", "3", "4", "5", "6"]:
            user_data["servicio"] = message_body
            user_data["stage"] = "especialista"
            especialista_menu = get_specialist_menu(message_body)
            if especialista_menu:
                send_whatsapp_message(phone_number, especialista_menu)
            else:
                send_whatsapp_message(phone_number, {"type": "text", "text": {"body": "Lo sentimos, no hay especialistas disponibles para este servicio en este momento."}})
                user_data["stage"] = "start"
        else:
            send_whatsapp_message(phone_number, {"type": "text", "text": {"body": "Por favor, elige una opción válida (1-7)."}})

    elif user_data["stage"] == "especialista":
        valid_specialists = ESPECIALISTAS_POR_SERVICIO.get(user_data["servicio"], [])
        if message_body in valid_specialists:
            user_data["especialista"] = message_body
            user_data["stage"] = "esperando_nombre"
            send_whatsapp_message(phone_number, {"type": "text", "text": {"body": "Excelente. Para continuar, por favor, envíame tu nombre completo."}})
        else:
            send_whatsapp_message(phone_number, {"type": "text", "text": {"body": "Por favor, elige un especialista válido de la lista."}})
    
    elif user_data["stage"] == "esperando_nombre":
        user_info["nombre"] = message_body.strip()
        user_data_storage[phone_number] = user_info
        user_data["stage"] = "esperando_telefono"
        send_whatsapp_message(phone_number, {"type": "text", "text": {"body": "Gracias. Ahora tu número de teléfono."}})

    elif user_data["stage"] == "esperando_telefono":
        user_info["telefono"] = message_body.strip()
        user_data_storage[phone_number] = user_info
        user_data["stage"] = "esperando_fecha_nacimiento"
        send_whatsapp_message(phone_number, {"type": "text", "text": {"body": "Tu fecha de nacimiento (DD-MM-AAAA)."}})

    elif user_data["stage"] == "esperando_fecha_nacimiento":
        user_info["fecha_nacimiento"] = message_body.strip()
        user_data_storage[phone_number] = user_info
        user_data["stage"] = "esperando_edad"
        send_whatsapp_message(phone_number, {"type": "text", "text": {"body": "Y por último, tu edad."}})
    
    elif user_data["stage"] == "esperando_edad":
        user_info["edad"] = message_body.strip()
        user_data_storage[phone_number] = user_info
        user_data["stage"] = "esperando_correo"
        send_whatsapp_message(phone_number, {"type": "text", "text": {"body": "Perfecto. Necesitamos tu correo electrónico para enviarte la confirmación."}})

    elif user_data["stage"] == "esperando_correo":
        email_match = re.search(r'[\w\.-]+@[\w\.-]+\.\w+', message_body)
        if email_match:
            user_info["correo"] = email_match.group(0)
            user_data_storage[phone_number] = user_info
            
            pago_info = {"type": "text", "text": {"body": ("Te compartimos una información importante: 📌\n"
                             "Para consultas de primera vez, solicitamos un anticipo de $500 MXN. El monto restante se cubrirá el día de tu consulta.\n"
                             "Esta medida nos permite asegurar tu lugar, ya que contamos con alta demanda.\n\n"
                             "Datos para pago:\n"
                             "Banco: BBVA\n"
                             "Cuenta: 048 482 8712\n"
                             "CLABE: 012180004848287122\n\n"
                             "⚠️ Por favor, envía tu comprobante de pago en este mismo chat para poder continuar con la agenda.")}}
            send_whatsapp_message(phone_number, pago_info)
            user_data["stage"] = "esperando_comprobante"
        else:
            send_whatsapp_message(phone_number, {"type": "text", "text": {"body": "El formato del correo es incorrecto. Por favor, inténtalo de nuevo."}})

    elif user_data["stage"] == "esperando_comprobante":
        send_whatsapp_message(phone_number, {"type": "text", "text": {"body": "✅ Comprobante recibido. ¡Gracias! Ahora, vamos a agendar."}})
        
        servicio_key = user_data.get("servicio", "1")
        duracion = DURACIONES_PRIMERA_VEZ.get(servicio_key, 60)
        
        mensaje_duracion = (f"La duración de esta cita es de {duracion} minutos.\n"
                            "Nuestros horarios generales son:\n"
                            "Lunes: 9:00–13:00 y 14:00-19:00\n"
                            "Miércoles: 15:00–20:00\n"
                            "Jueves: 9:00–12:00 y 15:00–18:00\n"
                            "Viernes: 9:00–15:00\n"
                            "Sábado: 10:00–11:30 (solo algunos servicios)\n\n"
                            "Por favor, indica la fecha y hora que deseas para tu cita (ej: 2025-09-15 10:00). Verificaremos la disponibilidad.")
                            
        send_whatsapp_message(phone_number, {"type": "text", "text": {"body": mensaje_duracion}})
        user_data["stage"] = "esperando_fecha"

    # === SUBSECUENTE (sin cambios) ===
    elif user_data["stage"] == "servicio_subsecuente":
        if message_body in ["1", "2", "3", "4", "5", "6"]:
            user_data["servicio"] = message_body
            user_data["stage"] = "esperando_nombre_sub"
            send_whatsapp_message(phone_number, {"type": "text", "text": {"body": "Por favor, envía tu nombre completo."}})
        elif message_body == "7":
            user_data["stage"] = "otros_opciones_sub"
            send_whatsapp_message(phone_number, OTROS_OPCIONES)
        else:
            send_whatsapp_message(phone_number, {"type": "text", "text": {"body": "Por favor, elige una opción válida (1-7)."}})

    elif user_data["stage"] == "otros_opciones_sub":
        if message_body == "3":
            send_whatsapp_message(phone_number, {"type": "text", "text": {"body": "Conectando con América... Un miembro del equipo te contactará pronto."}})
            user_data["stage"] = "start"
        else:
            user_data["servicio"] = message_body
            user_data["stage"] = "esperando_nombre_sub"
            send_whatsapp_message(phone_number, {"type": "text", "text": {"body": "Por favor, envía tu nombre completo."}})

    elif user_data["stage"] == "esperando_nombre_sub":
        user_info["nombre"] = message_body.strip()
        user_data_storage[phone_number] = user_info
        user_data["stage"] = "esperando_telefono_sub"
        send_whatsapp_message(phone_number, {"type": "text", "text": {"body": "Gracias. Ahora, por favor, envía tu número de teléfono."}})
    
    elif user_data["stage"] == "esperando_telefono_sub":
        user_info["telefono"] = message_body.strip()
        user_data_storage[phone_number] = user_info
        user_data["stage"] = "esperando_fecha_nacimiento_sub"
        send_whatsapp_message(phone_number, {"type": "text", "text": {"body": "Por favor, envía tu fecha de nacimiento (DD-MM-AAAA)."}})

    elif user_data["stage"] == "esperando_fecha_nacimiento_sub":
        user_info["fecha_nacimiento"] = message_body.strip()
        user_data_storage[phone_number] = user_info
        user_data["stage"] = "esperando_edad_sub"
        send_whatsapp_message(phone_number, {"type": "text", "text": {"body": "Por último, ¿cuántos años tienes?"}})

    elif user_data["stage"] == "esperando_edad_sub":
        user_info["edad"] = message_body.strip()
        user_data_storage[phone_number] = user_info
        user_data["stage"] = "esperando_correo_sub"
        send_whatsapp_message(phone_number, {"type": "text", "text": {"body": "Gracias. Ahora, por favor, envíanos tu correo electrónico para enviarte la confirmación."}})

    elif user_data["stage"] == "esperando_correo_sub":
        email_match = re.search(r'[\w\.-]+@[\w\.-]+\.\w+', message_body)
        if email_match:
            user_info["correo"] = email_match.group(0)
            user_data_storage[phone_number] = user_info
            send_whatsapp_message(phone_number, {"type": "text", "text": {"body": "Por favor, responde con la fecha y hora que prefieras (ej: 2025-04-05 10:00)"}})
            user_data["stage"] = "esperando_fecha_sub"
        else:
            send_whatsapp_message(phone_number, {"type": "text", "text": {"body": "El formato del correo es incorrecto. Por favor, inténtalo de nuevo."}})
    
    # === AGENDAR CITA (PRIMERA VEZ) ===
    elif user_data["stage"] == "esperando_fecha":
        try:
            fecha_hora_str = message_body.strip()
            fecha_hora = datetime.strptime(fecha_hora_str, "%Y-%m-%d %H:%M")
            servicio_key = user_data.get("servicio", "1")
            duracion = DURACIONES_PRIMERA_VEZ.get(servicio_key, 60)
            servicio_nombre = SERVICIOS_NOMBRES.get(servicio_key, "Consulta")
            especialista_key = user_data.get("especialista", "1")
            especialista_nombre = ESPECIALISTAS_NOMBRES.get(especialista_key, "No definido")
            nombre_paciente = user_info.get('nombre', 'Paciente Anónimo')

            descripcion = f"Paciente: {nombre_paciente}\nTeléfono: {user_info.get('telefono', 'No proporcionado')}\nServicio: {servicio_nombre}\nEspecialista: {especialista_nombre}".strip()

            crear_evento_google_calendar(
                f"Cita - {servicio_nombre} con {especialista_nombre}",
                fecha_hora, duracion, descripcion
            )
            send_appointment_email(
                user_info.get('correo'), EMAIL_ADDRESS, servicio_nombre, nombre_paciente,
                user_info.get('telefono'), user_info.get('fecha_nacimiento'),
                user_info.get('edad'), especialista_nombre,
                fecha_hora.strftime("%Y-%m-%d"), fecha_hora.strftime("%H:%M")
            )

            send_whatsapp_message(phone_number, CONFIRMACION)
            cita_detalle = {"type": "text", "text": {"body": f"📅 CONFIRMACIÓN DE CITA\n\nServicio: {servicio_nombre}\nEspecialista: {especialista_nombre}\nFecha y hora: {fecha_hora_str}\nDuración estimada: {duracion} minutos"}}
            send_whatsapp_message(phone_number, cita_detalle)
            
            if phone_number in user_state: del user_state[phone_number]
            if phone_number in user_data_storage: del user_data_storage[phone_number]

        except ValueError:
            send_whatsapp_message(phone_number, {"type": "text", "text": {"body": "Por favor, envía la fecha y hora en formato: AAAA-MM-DD HH:MM\nEj: 2025-04-05 10:00"}})

    # === AGENDAR CITA (SUBSECUENTE) ===
    elif user_data["stage"] == "esperando_fecha_sub":
        try:
            fecha_hora_str = message_body.strip()
            fecha_hora = datetime.strptime(fecha_hora_str, "%Y-%m-%d %H:%M")
            servicio_key = user_data.get("servicio", "1")
            duracion = DURACIONES_SUBSECUENTE.get(servicio_key, 45)
            servicio_nombre = SERVICIOS_SUB_NOMBRES.get(servicio_key, "Consulta")
            nombre_paciente = user_info.get('nombre', 'Paciente Anónimo')
            especialista_nombre = "Por definir"

            descripcion = f"Paciente: {nombre_paciente}\nTeléfono: {user_info.get('telefono', 'No proporcionado')}\nServicio: {servicio_nombre}".strip()

            crear_evento_google_calendar(
                f"Cita - {servicio_nombre} (Subsecuente)",
                fecha_hora, duracion, descripcion
            )
            send_appointment_email(
                user_info.get('correo'), EMAIL_ADDRESS, servicio_nombre, nombre_paciente,
                user_info.get('telefono'), user_info.get('fecha_nacimiento'),
                user_info.get('edad'), especialista_nombre,
                fecha_hora.strftime("%Y-%m-%d"), fecha_hora.strftime("%H:%M")
            )
            send_whatsapp_message(phone_number, CONFIRMACION)
            cita_detalle = {"type": "text", "text": {"body": f"📅 CONFIRMACIÓN DE CITA\n\nServicio: {servicio_nombre}\nFecha y hora: {fecha_hora_str}\nDuración estimada: {duracion} minutos"}}
            send_whatsapp_message(phone_number, cita_detalle)

            if phone_number in user_state: del user_state[phone_number]
            if phone_number in user_data_storage: del user_data_storage[phone_number]

        except ValueError:
            send_whatsapp_message(phone_number, {"type": "text", "text": {"body": "Por favor, envía la fecha y hora en formato: AAAA-MM-DD HH:MM\nEj: 2025-04-05 10:00"}})

    # === OTROS FLUJOS ===
    elif user_data["stage"] == "atencion_cliente":
        if message_body == "1": send_whatsapp_message(phone_number, COSTOS)
        elif message_body == "2": send_whatsapp_message(phone_number, {"type": "text", "text": {"body": "Conectando con América... Un miembro del equipo te contactará pronto."}})
        user_data["stage"] = "start"

    elif user_data["stage"] == "facturacion":
        if message_body == "1": send_whatsapp_message(phone_number, {"type": "text", "text": {"body": "Por favor, completa el formulario:\n🔗 [Formulario de facturación](https://docs.google.com/forms/d/e/1FAIpQLSfr1WWXWQGx4sZj3_0FnIp6XWBb1mol4GfVGfymflsRI0E5pA/viewform)"}})
        elif message_body == "2": send_whatsapp_message(phone_number, {"type": "text", "text": {"body": "Para dudas de facturación, escribe a:\n📧 lcastillo@gbcasesoria.mx"}})
        user_data["stage"] = "start"

    else:
        user_data["stage"] = "start"

    # Si el estado es 'start', reiniciar con el mensaje de bienvenida
    if user_data["stage"] == "start":
        send_whatsapp_message(phone_number, WELCOME_MESSAGE)
        user_data["stage"] = "option_selected"

    user_state[phone_number] = user_data

# === WEBHOOKS ===
@application.route('/webhook/', methods=['GET', 'POST'])
def webhook():
    if request.method == 'GET':
        mode = request.args.get('hub.mode')
        token = request.args.get('hub.verify_token')
        challenge = request.args.get('hub.challenge')
        if mode and token and mode == 'subscribe' and token == META_VERIFY_TOKEN:
            return challenge
        else:
            return 'Verificación fallida', 403
    elif request.method == 'POST':
        try:
            # Línea añadida para depuración
            print("Datos brutos de la solicitud:", request.get_data())
            
            data = request.get_json()
            if data.get('entry'):
                for entry in data['entry']:
                    for change in entry['changes']:
                        if change.get('value', {}).get('messages'):
                            for message in change['value']['messages']:
                                phone_number = message['from']
                                # Adaptar para manejar imágenes en el futuro
                                message_body = message.get('text', {}).get('body', '')
                                if not message_body:
                                    # Aquí se podría manejar si es una imagen, audio, etc.
                                    # Si el estado es 'esperando_comprobante', se procesaría aquí.
                                    pass
                                process_user_message(phone_number, message_body)
            return 'EVENT_RECEIVED', 200
        except Exception as e:
            print(f"❌ Error en webhook: {e}")
            return 'Error', 500

# === ENDPOINT PARA RECORDATORIOS DIARIOS ===
@application.route('/send-reminders', methods=['GET'])
def send_reminders():
    if REMINDER_TOKEN and request.args.get('token') != REMINDER_TOKEN:
        return jsonify({"error": "Acceso no autorizado"}), 403

    try:
        service = get_calendar_service()
        if not service:
            return jsonify({"error": "No se pudo conectar al servicio de Google Calendar"}), 500

        tomorrow = datetime.now() + timedelta(days=1)
        start_of_day = tomorrow.replace(hour=0, minute=0, second=0, microsecond=0)
        end_of_day = tomorrow.replace(hour=23, minute=59, second=59, microsecond=999)
        time_min, time_max = start_of_day.isoformat() + 'Z', end_of_day.isoformat() + 'Z'

        events_result = service.events().list(calendarId=GOOGLE_CALENDAR_ID, timeMin=time_min, timeMax=time_max, singleEvents=True, orderBy='startTime').execute()
        events = events_result.get('items', [])
        reminders_sent = []

        for event in events:
            description = event.get('description', '')
            phone_match = re.search(r'Teléfono:\s*(\+?\d+)', description)
            name_match = re.search(r'Paciente:\s*([^\n]+)', description)
            service_match = re.search(r'Servicio:\s*([^\n]+)', description)

            if not phone_match: continue

            patient_name = name_match.group(1).strip() if name_match else "Paciente"
            phone_number = phone_match.group(1).strip()
            service_name = service_match.group(1).strip() if service_match else "tu cita"
            
            start_time = event['start'].get('dateTime', event['start'].get('date'))
            event_datetime = datetime.fromisoformat(start_time.replace('Z', '+00:00')).astimezone()
            formatted_time = event_datetime.strftime("%H:%M")
            formatted_date = event_datetime.strftime("%d de %B")

            reminder_message = {"type": "text", "text": {"body": f"📅 *Recordatorio de Cita* – Milkiin ❤️\n\nHola {patient_name},\n\nTe recordamos tu cita programada para mañana, *{formatted_date}* a las *{formatted_time}* hrs.\n\n🔹 Servicio: {service_name}\n📍 Insurgentes Sur 1160, 6º piso, Colonia Del Valle\n\n⏰ Por favor, llega 10 minutos antes.\n\n¡Te esperamos con cariño! 💕"}}
            
            response = send_whatsapp_message(phone_number, reminder_message)
            reminders_sent.append({"phone": phone_number, "status": "sent" if response else "failed"})

        return jsonify({"message": f"Recordatorios procesados: {len(reminders_sent)}", "details": reminders_sent}), 200

    except Exception as e:
        print(f"❌ Error al enviar recordatorios: {e}")
        return jsonify({"error": str(e)}), 500

@application.route('/')
def home():
    return jsonify({"message": "🤖 Bot de WhatsApp para Milkiin usando Meta API está activo", "status": "✅ Online"})

if __name__ == "__main__":
    application.run(debug=True)