from flask import Flask, request, jsonify
import requests
import json
import re
from datetime import datetime, timedelta, time
import os
import smtplib
import ssl
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from pytz import timezone

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
SCOPES = ['https://www.googleapis.com/auth/calendar.events.readonly', 'https://www.googleapis.com/auth/calendar.events']
MEXICO_TIMEZONE = timezone('America/Mexico_City')

# === CONFIGURACIÓN DE CORREO ELECTRÓNICO ===
EMAIL_ADDRESS = os.environ.get('EMAIL_ADDRESS')
EMAIL_PASSWORD = os.environ.get('EMAIL_PASSWORD')
SMTP_SERVER = 'smtp.gmail.com'
SMTP_PORT = 465

# === TOKEN DE SEGURIDAD PARA RECORDATORIOS (opciónal) ===
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
        "body": "Bienvenido(a) a Milkiin.\nEstamos aquí para brindarte la mejor atención.\n\nSelecciona el número de la opción que corresponda a tu necesidad:\n1- Paciente de primera vez\n2- Paciente subsecuente\n3- Atención al cliente\n4- Facturación\n5- Envío de resultados\n6- Dudas, preguntas y cancelaciones\n\nPor favor, responde con el número de la opción que elijas."
    }
}

SERVICIOS_PRIMERA_VEZ = {
    "type": "text",
    "text": {
        "body": ("Selecciona el número de servicio de primera vez:\n"
                 "1. Fertilidad\n"
                 "2. Síndrome de Ovario Poliquístico\n"
                 "3. Chequeo Anual\n"
                 "4. Embarazo\n"
                 "5. Ginecología Pediátrica y Adolescentes\n"
                 "6. Revisión de Estudios\n"
                 "7. Agendar Espermatobioscopia con América")
    }
}

SERVICIOS_SUBSECUENTE = {
    "type": "text",
    "text": {
        "body": "Selecciona el servicio subsecuente:\n1️1 Fertilidad\n2️2 Síndrome de Ovario Poliquístico\n3️3 Chequeo Anual\n4️ Embarazo\n5️5 Revisión de estudios\n6️6 Seguimiento folicular\n7️7 Otros"
    }
}

OTROS_opciónES = {
    "type": "text",
    "text": {
        "body": "Selecciona una opción:\n1️1 Espermabiopsia directa\n2️2 Ginecología Pediátrica y Adolescentes\n3️3 Hablar con América"
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
    "6": ["1"]
}

def get_specialist_menu(service_key):
    especialistas_disponibles = ESPECIALISTAS_POR_SERVICIO.get(service_key, [])
    if not especialistas_disponibles:
        return None
    menu_text = "Selecciona el número de la opción que corresponde a tu espcialista:\n"
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

# Duraciones de cita para primera vez
DURACIONES_PRIMERA_VEZ = {
    "1": 30, # Fertilidad - 30 minutos
    "2": 60, # Síndrome de Ovario Poliquístico - 60 minutos
    "3": 60, # Chequeo Anual - 60 minutos
    "4": 60, # Embarazo - 60 minutos
    "5": 60, # Ginecología Pediátrica y Adolescentes - 60 minutos
    "6": 30  # Revisión de Estudios - 30 minutos
}

# Duraciones de cita para subsecuente
DURACIONES_SUBSECUENTE = {
    "1": 30, # Fertilidad - 30 minutos
    "2": 45, # Síndrome de Ovario Poliquístico - 45 minutos
    "3": 45, # Chequeo Anual - 45 minutos
    "4": 45, # Embarazo - 45 minutos
    "5": 30, # Revisión de estudios - 30 minutos
    "6": 30, # Seguimiento folicular - 30 minutos
    "7": 30  # Otros - 30 minutos
}

# Horarios de la clínica por día (Lunes a Sábado)
HORARIOS_POR_DIA = {
    0: [('09:00', '13:00'), ('14:00', '19:00')],  # Lunes
    1: [('09:00', '19:00')],  # Martes
    2: [('15:00', '20:00')],  # Miércoles
    3: [('09:00', '12:00'), ('15:00', '18:00')],  # Jueves
    4: [('09:00', '15:00')],  # Viernes
    5: [('10:00', '11:30')]   # Sábado
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

def get_available_slots(date_str, duration_minutes):
    try:
        service = get_calendar_service()
        if not service:
            print("❌ Error: No se pudo conectar al servicio de Google Calendar.")
            return []

        date = datetime.strptime(date_str, "%Y-%m-%d").date()
        day_of_week = date.weekday()
        
        horarios_disponibles = HORARIOS_POR_DIA.get(day_of_week, [])
        if not horarios_disponibles:
            print(f"DEBUG: No hay horarios configurados para el día {date.strftime('%A')}.")
            return []
        
        print(f"DEBUG: Horarios de la clínica para el día {date.strftime('%A')} ({day_of_week}): {horarios_disponibles}")

        start_of_day_utc = MEXICO_TIMEZONE.localize(datetime.combine(date, time.min)).astimezone(timezone('UTC'))
        end_of_day_utc = MEXICO_TIMEZONE.localize(datetime.combine(date, time.max)).astimezone(timezone('UTC'))

        events_result = service.events().list(
            calendarId=GOOGLE_CALENDAR_ID,
            timeMin=start_of_day_utc.isoformat(),
            timeMax=end_of_day_utc.isoformat(),
            singleEvents=True,
            orderBy='startTime'
        ).execute()
        
        events = events_result.get('items', [])
        print(f"DEBUG: Eventos encontrados en el calendario para {date_str}: {len(events)}")
        
        occupied_slots = []
        for event in events:
            start_time_str = event['start'].get('dateTime')
            end_time_str = event['end'].get('dateTime')
            start_date_str = event['start'].get('date')
            end_date_str = event['end'].get('date')

            if start_time_str and end_time_str:
                start_time_mx = datetime.fromisoformat(start_time_str).astimezone(MEXICO_TIMEZONE)
                end_time_mx = datetime.fromisoformat(end_time_str).astimezone(MEXICO_TIMEZONE)
                occupied_slots.append((start_time_mx, end_time_mx))
            elif start_date_str and end_date_str:
                occupied_slots.append((
                    datetime.combine(date, time.min).astimezone(MEXICO_TIMEZONE),
                    datetime.combine(date, time.max).astimezone(MEXICO_TIMEZONE)
                ))
        
        print(f"DEBUG: Slots ocupados (ajustados a MX): {occupied_slots}")
        
        available_slots = []
        for start_time_str, end_time_str in horarios_disponibles:
            current_time = datetime.combine(date, datetime.strptime(start_time_str, "%H:%M").time()).astimezone(MEXICO_TIMEZONE)
            end_of_period = datetime.combine(date, datetime.strptime(end_time_str, "%H:%M").time()).astimezone(MEXICO_TIMEZONE)
            
            while current_time + timedelta(minutes=duration_minutes) <= end_of_period:
                is_available = True
                proposed_end_time = current_time + timedelta(minutes=duration_minutes)
                
                for occupied_start, occupied_end in occupied_slots:
                    if (current_time < occupied_end and proposed_end_time > occupied_start):
                        is_available = False
                        current_time = occupied_end
                        break
                
                if is_available:
                    available_slots.append(current_time)
                
                current_time += timedelta(minutes=duration_minutes)
        
        print(f"DEBUG: Slots disponibles calculados: {len(available_slots)}")
        print(f"DEBUG: Slots disponibles: {[slot.strftime('%H:%M') for slot in sorted(list(set(available_slots)))]}")
        return [slot.strftime("%H:%M") for slot in sorted(list(set(available_slots)))]

    except HttpError as error:
        print(f"❌ Error HTTP al obtener disponibilidad: {error}")
        return []
    except Exception as e:
        print(f"❌ Error desconocido al obtener disponibilidad: {e}")
        return []

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
def process_user_message(phone_number, message_body, is_media=False):
    global user_state, user_data_storage
    user_state_obj = user_state.get(phone_number, {"stage": "start"})
    user_info = user_data_storage.get(phone_number, {})
    print(f"[MENSAJE ENTRANTE] {phone_number}: {message_body}")

    # Manejar el timeout del comprobante primero
    if user_state_obj.get("stage") == "esperando_comprobante":
        timestamp = user_state_obj.get("timestamp")
        if timestamp and (datetime.now() - timestamp).total_seconds() > 300:
            send_whatsapp_message(phone_number, {"type": "text", "text": {"body": "⏰ Tu tiempo para enviar el comprobante ha expirado. Por favor, reinicia la conversación."}})
            if phone_number in user_state: del user_state[phone_number]
            return

    # Reiniciar la conversación si el usuario dice "hola"
    if message_body.lower() == "hola" and user_state_obj["stage"] != "start":
        user_state_obj["stage"] = "start"
        if phone_number in user_data_storage: del user_data_storage[phone_number]
    
    # === Lógica de la conversación ===
    if user_state_obj["stage"] == "start":
        send_whatsapp_message(phone_number, WELCOME_MESSAGE)
        user_state_obj["stage"] = "option_selected"

    elif user_state_obj["stage"] == "option_selected":
        if message_body == "1":
            user_state_obj["tipo"] = "primera_vez"
            user_state_obj["stage"] = "servicio_primera"
            send_whatsapp_message(phone_number, SERVICIOS_PRIMERA_VEZ)
        elif message_body == "2":
            user_state_obj["tipo"] = "subsecuente"
            user_state_obj["stage"] = "servicio_subsecuente"
            send_whatsapp_message(phone_number, SERVICIOS_SUBSECUENTE)
        elif message_body == "3":
            user_state_obj["stage"] = "atencion_cliente"
            send_whatsapp_message(phone_number, {"type": "text", "text": {"body": "1. COSTOS\n2. Hablar con América"}})
        elif message_body == "4":
            user_state_obj["stage"] = "facturacion"
            send_whatsapp_message(phone_number, {"type": "text", "text": {"body": "1. Requiero factura\n2. Dudas de Facturacion"}})
        elif message_body == "5":
            send_whatsapp_message(phone_number, {"type": "text", "text": {"body": "Para el envío de resultados, envíalos al correo:\n📧 nicontacto@heyginemoni.com"}})
            user_state_obj["stage"] = "start"
        elif message_body == "6":
            send_whatsapp_message(phone_number, {"type": "text", "text": {"body": "Para dudas o cancelaciones, puedes escribirnos a:\n📧 contacto@heyginemoni.com"}})
            user_state_obj["stage"] = "start"
        else:
            send_whatsapp_message(phone_number, {"type": "text", "text": {"body": "Por favor, selecciona una opción válida del 1 al 6."}})

    # === Flujo de primera vez ===
    elif user_state_obj["stage"] == "servicio_primera":
        if message_body in ["1", "2", "3", "4", "5", "6"]:
            user_state_obj["servicio"] = message_body
            user_state_obj["stage"] = "esperando_especialista"
            especialista_menu = get_specialist_menu(message_body)
            if especialista_menu:
                send_whatsapp_message(phone_number, especialista_menu)
            else:
                send_whatsapp_message(phone_number, {"type": "text", "text": {"body": "Lo sentimos, no hay especialistas disponibles para este servicio."}})
                user_state_obj["stage"] = "start"
        elif message_body == "7":
            send_whatsapp_message(phone_number, {"type": "text", "text": {"body": "Claro, en un momento uno de nuestros asesores te atenderá para agendar tu cita de Espermatobioscopia. Gracias."}})
            user_state_obj["stage"] = "start"
        else:
            send_whatsapp_message(phone_number, {"type": "text", "text": {"body": "Por favor, elige una opción válida (1-7)."}})

    elif user_state_obj["stage"] == "esperando_especialista":
        valid_specialists = ESPECIALISTAS_POR_SERVICIO.get(user_state_obj["servicio"], [])
        if message_body in valid_specialists:
            user_state_obj["especialista"] = message_body
            user_state_obj["stage"] = "esperando_nombre"
            send_whatsapp_message(phone_number, {"type": "text", "text": {"body": "Excelente. Para continuar, por favor, envíame tu nombre completo."}})
        else:
            send_whatsapp_message(phone_number, {"type": "text", "text": {"body": "Por favor, elige un especialista válido de la lista."}})
    
    elif user_state_obj["stage"] == "esperando_nombre":
        user_info["nombre"] = message_body.strip()
        user_state_obj["stage"] = "esperando_telefono"
        user_data_storage[phone_number] = user_info
        send_whatsapp_message(phone_number, {"type": "text", "text": {"body": "Gracias. Ahora tu número de teléfono."}})

    elif user_state_obj["stage"] == "esperando_telefono":
        if re.match(r'^\d{10,}$', re.sub(r'\D', '', message_body)):
            user_info["telefono"] = re.sub(r'\D', '', message_body)
            user_state_obj["stage"] = "esperando_fecha_nacimiento"
            user_data_storage[phone_number] = user_info
            send_whatsapp_message(phone_number, {"type": "text", "text": {"body": "Tu fecha de nacimiento (DD-MM-AAAA)."}})
        else:
            send_whatsapp_message(phone_number, {"type": "text", "text": {"body": "Por favor, ingresa un número de teléfono válido (al menos 10 dígitos)."}})

    elif user_state_obj["stage"] == "esperando_fecha_nacimiento":
        user_info["fecha_nacimiento"] = message_body.strip()
        user_state_obj["stage"] = "esperando_edad"
        user_data_storage[phone_number] = user_info
        send_whatsapp_message(phone_number, {"type": "text", "text": {"body": "Y por último, tu edad."}})
    
    elif user_state_obj["stage"] == "esperando_edad":
        if message_body.isdigit():
            user_info["edad"] = message_body.strip()
            user_state_obj["stage"] = "esperando_correo"
            user_data_storage[phone_number] = user_info
            send_whatsapp_message(phone_number, {"type": "text", "text": {"body": "Perfecto. Necesitamos tu correo electrónico para enviarte la confirmación."}})
        else:
            send_whatsapp_message(phone_number, {"type": "text", "text": {"body": "Por favor, ingresa tu edad en números."}})

    elif user_state_obj["stage"] == "esperando_correo":
        email_match = re.search(r'[\w\.-]+@[\w\.-]+\.\w+', message_body)
        if email_match:
            user_info["correo"] = email_match.group(0)
            user_state_obj["stage"] = "esperando_comprobante"
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
            user_state_obj["timestamp"] = datetime.now()
        else:
            send_whatsapp_message(phone_number, {"type": "text", "text": {"body": "El formato del correo es incorrecto. Por favor, inténtalo de nuevo."}})

    elif user_state_obj["stage"] == "esperando_comprobante":
        pass

    elif user_state_obj["stage"] == "esperando_fecha_disponibilidad":
        try:
            fecha_str = message_body.strip()
            fecha_futura = datetime.strptime(fecha_str, "%Y-%m-%d").date()
            if fecha_futura < datetime.now().date():
                send_whatsapp_message(phone_number, {"type": "text", "text": {"body": "❌ Por favor, elige una fecha futura."}})
                return
            
            duracion = DURACIONES_PRIMERA_VEZ.get(user_state_obj["servicio"], 60)
            servicio_nombre = SERVICIOS_NOMBRES.get(user_state_obj["servicio"], "Consulta")
            available_slots = get_available_slots(fecha_str, duracion)
            
            if available_slots:
                slots_text = "\n".join([f"⏰ {slot}" for slot in available_slots])
                user_info["fecha_elegida"] = fecha_str
                user_state_obj["stage"] = "esperando_hora"
                user_data_storage[phone_number] = user_info
                
                menu_disponibilidad = {"type": "text", "text": {"body": f"✅ La duración de la cita para '{servicio_nombre}' es de {duracion} minutos.\n\nHorarios disponibles para el {fecha_str}:\n\n{slots_text}\n\nPor favor, responde con la hora que prefieras (ej: 10:00)."}}
                send_whatsapp_message(phone_number, menu_disponibilidad)
            else:
                send_whatsapp_message(phone_number, {"type": "text", "text": {"body": f"❌ Lo sentimos, no hay horarios disponibles para el {fecha_str}. Por favor, elige otra fecha."}})
        except ValueError:
            send_whatsapp_message(phone_number, {"type": "text", "text": {"body": "Por favor, envía la fecha en formato AAAA-MM-DD. Ej: 2025-09-15"}})

    elif user_state_obj["stage"] == "esperando_hora":
        try:
            hora_str = message_body.strip()
            fecha_str = user_info.get("fecha_elegida")
            if not fecha_str:
                send_whatsapp_message(phone_number, {"type": "text", "text": {"body": "❌ Hubo un error. Por favor, reinicia la conversación enviando 'hola'."}})
                return
            
            fecha_hora = MEXICO_TIMEZONE.localize(datetime.strptime(f"{fecha_str} {hora_str}", "%Y-%m-%d %H:%M"))
            duracion = DURACIONES_PRIMERA_VEZ.get(user_state_obj["servicio"], 60)
            available_slots = get_available_slots(fecha_str, duracion)
            
            if hora_str not in available_slots:
                send_whatsapp_message(phone_number, {"type": "text", "text": {"body": f"❌ La hora {hora_str} no está disponible. Por favor, elige una de las opciones que te mostramos."}})
                return
            
            servicio_nombre = SERVICIOS_NOMBRES.get(user_state_obj["servicio"], "Consulta")
            especialista_key = user_state_obj.get("especialista", "1")
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
            cita_detalle = {"type": "text", "text": {"body": f"📅 CONFIRMACIÓN DE CITA\n\nServicio: {servicio_nombre}\nEspecialista: {especialista_nombre}\nFecha y hora: {fecha_hora.strftime('%Y-%m-%d %H:%M')}\nDuración estimada: {duracion} minutos"}}
            send_whatsapp_message(phone_number, cita_detalle)
            
            if phone_number in user_state: del user_state[phone_number]
            if phone_number in user_data_storage: del user_data_storage[phone_number]
            
        except ValueError:
            send_whatsapp_message(phone_number, {"type": "text", "text": {"body": "Por favor, envía la hora en formato HH:MM.\nEj: 10:00"}})

    # === Flujo de subsecuente (simplificado y sin validación de disponibilidad) ===
    elif user_state_obj["stage"] == "servicio_subsecuente":
        if message_body in ["1", "2", "3", "4", "5", "6"]:
            user_state_obj["servicio"] = message_body
            user_state_obj["stage"] = "esperando_nombre_sub"
            send_whatsapp_message(phone_number, {"type": "text", "text": {"body": "Por favor, envía tu nombre completo."}})
        elif message_body == "7":
            user_state_obj["stage"] = "otros_opciones_sub"
            send_whatsapp_message(phone_number, OTROS_opciónES)
        else:
            send_whatsapp_message(phone_number, {"type": "text", "text": {"body": "Por favor, elige una opción válida (1-7)."}})

    elif user_state_obj["stage"] == "otros_opciones_sub":
        if message_body == "3":
            send_whatsapp_message(phone_number, {"type": "text", "text": {"body": "Conectando con América... Un miembro del equipo te contactará pronto."}})
            user_state_obj["stage"] = "start"
        else:
            user_state_obj["servicio"] = message_body
            user_state_obj["stage"] = "esperando_nombre_sub"
            user_state_obj["especialista"] = "No definido"
            send_whatsapp_message(phone_number, {"type": "text", "text": {"body": "Por favor, envía tu nombre completo."}})

    elif user_state_obj["stage"] == "esperando_nombre_sub":
        user_info["nombre"] = message_body.strip()
        user_data_storage[phone_number] = user_info
        user_state_obj["stage"] = "esperando_telefono_sub"
        send_whatsapp_message(phone_number, {"type": "text", "text": {"body": "Gracias. Ahora, por favor, envía tu número de teléfono."}})
    
    elif user_state_obj["stage"] == "esperando_telefono_sub":
        if re.match(r'^\d{10,}$', re.sub(r'\D', '', message_body)):
            user_info["telefono"] = re.sub(r'\D', '', message_body)
            user_state_obj["stage"] = "esperando_fecha_nacimiento_sub"
            user_data_storage[phone_number] = user_info
            send_whatsapp_message(phone_number, {"type": "text", "text": {"body": "Por favor, envía tu fecha de nacimiento (DD-MM-AAAA)."}})
        else:
            send_whatsapp_message(phone_number, {"type": "text", "text": {"body": "Por favor, ingresa un número de teléfono válido (al menos 10 dígitos)."}})

    elif user_state_obj["stage"] == "esperando_fecha_nacimiento_sub":
        user_info["fecha_nacimiento"] = message_body.strip()
        user_data_storage[phone_number] = user_info
        user_state_obj["stage"] = "esperando_edad_sub"
        send_whatsapp_message(phone_number, {"type": "text", "text": {"body": "Por último, ¿cuántos años tienes?"}})

    elif user_state_obj["stage"] == "esperando_edad_sub":
        if message_body.isdigit():
            user_info["edad"] = message_body.strip()
            user_data_storage[phone_number] = user_info
            user_state_obj["stage"] = "esperando_correo_sub"
            send_whatsapp_message(phone_number, {"type": "text", "text": {"body": "Gracias. Ahora, por favor, envíanos tu correo electrónico para enviarte la confirmación."}})
        else:
            send_whatsapp_message(phone_number, {"type": "text", "text": {"body": "Por favor, ingresa tu edad en números."}})

    elif user_state_obj["stage"] == "esperando_correo_sub":
        email_match = re.search(r'[\w\.-]+@[\w\.-]+\.\w+', message_body)
        if email_match:
            user_info["correo"] = email_match.group(0)
            user_state_obj["stage"] = "esperando_fecha_hora_sub"
            user_data_storage[phone_number] = user_info
            send_whatsapp_message(phone_number, {"type": "text", "text": {"body": "Perfecto, ahora por favor, dinos qué fecha y hora te gustaría agendar (ej: 2025-09-15 10:00)."}})
        else:
            send_whatsapp_message(phone_number, {"type": "text", "text": {"body": "El formato del correo es incorrecto. Por favor, inténtalo de nuevo."}})

    elif user_state_obj["stage"] == "esperando_fecha_hora_sub":
        try:
            fecha_hora_str = message_body.strip()
            fecha_hora = MEXICO_TIMEZONE.localize(datetime.strptime(fecha_hora_str, "%Y-%m-%d %H:%M"))
            tipo_cita = user_state_obj.get("tipo")
            servicio_key = user_state_obj.get("servicio", "1")
            
            duracion = DURACIONES_SUBSECUENTE.get(servicio_key, 45)
            servicio_nombre = SERVICIOS_SUB_NOMBRES.get(servicio_key, "Consulta")
            especialista_nombre = "No definido"
            
            nombre_paciente = user_info.get('nombre', 'Paciente Anónimo')
            descripcion = f"Paciente: {nombre_paciente}\nTeléfono: {user_info.get('telefono', 'No proporcionado')}\nServicio: {servicio_nombre}\nEspecialista: {especialista_nombre}".strip()
            
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
            cita_detalle = {"type": "text", "text": {"body": f"📅 CONFIRMACIÓN DE CITA\n\nServicio: {servicio_nombre}\nFecha y hora: {fecha_hora.strftime('%Y-%m-%d %H:%M')}\nDuración estimada: {duracion} minutos"}}
            send_whatsapp_message(phone_number, cita_detalle)
            
            if phone_number in user_state: del user_state[phone_number]
            if phone_number in user_data_storage: del user_data_storage[phone_number]
        except ValueError:
            send_whatsapp_message(phone_number, {"type": "text", "text": {"body": "Por favor, envía la fecha y hora en el formato correcto: AAAA-MM-DD HH:MM. Ej: 2025-09-15 10:00"}})

    # === Otros flujos ===
    elif user_state_obj["stage"] == "atencion_cliente":
        if message_body == "1": send_whatsapp_message(phone_number, COSTOS)
        elif message_body == "2": send_whatsapp_message(phone_number, {"type": "text", "text": {"body": "Conectando con América... Un miembro del equipo te contactará pronto."}})
        user_state_obj["stage"] = "start"

    elif user_state_obj["stage"] == "facturacion":
        if message_body == "1": send_whatsapp_message(phone_number, {"type": "text", "text": {"body": "Por favor, completa el formulario:\n🔗 [Formulario de facturación](https://docs.google.com/forms/d/e/1FAIpQLSfr1WWXWQGx4sZj3_0FnIp6XWBb1mol4GfVGfymflsRI0E5pA/viewform)"}})
        elif message_body == "2": send_whatsapp_message(phone_number, {"type": "text", "text": {"body": "Para dudas de facturación, escribe a:\n📧 lcastillo@gbcasesoria.mx"}})
        user_state_obj["stage"] = "start"
    
    # Manejo de casos no esperados
    else:
        send_whatsapp_message(phone_number, WELCOME_MESSAGE)
        user_state_obj["stage"] = "option_selected"

    user_state[phone_number] = user_state_obj

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
            print("Datos brutos de la solicitud:", request.get_data())
            
            data = request.get_json()
            if data.get('entry'):
                for entry in data['entry']:
                    for change in entry['changes']:
                        if change.get('value', {}).get('messages'):
                            for message in change['value']['messages']:
                                phone_number = message['from']
                                message_body = message.get('text', {}).get('body', '')
                                
                                is_media = False
                                mime_type = None
                                if message.get('image'):
                                    mime_type = message['image']['mime_type']
                                    is_media = True
                                elif message.get('document'):
                                    mime_type = message['document']['mime_type']
                                    is_media = True
                                
                                # Manejar el comprobante de pago
                                if user_state.get(phone_number, {}).get("stage") == "esperando_comprobante":
                                    timestamp = user_state[phone_number].get("timestamp")
                                    if timestamp and (datetime.now() - timestamp).total_seconds() > 300:
                                        send_whatsapp_message(phone_number, {"type": "text", "text": {"body": "⏰ Tu tiempo para enviar el comprobante ha expirado. Por favor, reinicia la conversación."}})
                                        if phone_number in user_state: del user_state[phone_number]
                                        return 'EVENT_RECEIVED', 200
                                    
                                    if is_media:
                                        if mime_type in ["image/png", "image/jpeg", "image/jpg", "application/pdf"]:
                                            user_state[phone_number]["stage"] = "esperando_fecha_disponibilidad"
                                            send_whatsapp_message(phone_number, {"type": "text", "text": {"body": "✅ Comprobante recibido. ¡Gracias! Ahora, por favor, indícanos la fecha de tu preferencia para la cita (ej: 2025-09-15)."}})
                                        else:
                                            send_whatsapp_message(phone_number, {"type": "text", "text": {"body": "❌ El formato del archivo no es válido. Por favor, sube una imagen (PNG, JPG) o un PDF."}})
                                    else:
                                        send_whatsapp_message(phone_number, {"type": "text", "text": {"body": "❌ Por favor, sube un archivo (imagen o PDF) como comprobante de pago, no texto."}})
                                        
                                elif message_body:
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
            event_datetime = datetime.fromisoformat(start_time.replace('Z', '+00:00')).astimezone(MEXICO_TIMEZONE)
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