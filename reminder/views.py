import urllib2, urllib, json, traceback
from collections import defaultdict
from datetime import date, datetime
from django.shortcuts import render
from django.http import HttpResponse, HttpResponseRedirect
from django.contrib import auth
from django.core.mail import EmailMessage
from models import Reminder
from forms import AddReminderForm


def manage(request):
    user_id = None
    if request.user.is_authenticated():
        user_id = request.user.id
    else:
        return HttpResponseRedirect("/accounts/login/")
    if request.method == 'POST':
        post_form = AddReminderForm(request.POST)
        if post_form.is_valid():
            zipcode = post_form.cleaned_data['zipcode']
            reminder = post_form.cleaned_data['reminder']
            Reminder.objects.create(user_id=user_id, zipcode=zipcode, warning_event=reminder)
    reminders = Reminder.objects.filter(user_id=user_id)
    form = AddReminderForm()
    return render(request, 'manage.html', {'form': form, 'reminders': reminders, 'logged_in': True})


def del_reminder(request):
    if not request.user.is_authenticated():
        return HttpResponseRedirect("/accounts/login/")
    try:
        reminder_id = int(request.GET.get('id', ''))
        p = Reminder.objects.get(id=int(reminder_id))
        p.delete()
    except:
        pass
    return HttpResponseRedirect("/")


def get_weather(zipcode):
    key = 'API_KEY'  # replace with your own API key
    baseurl = 'http://api.apixu.com/v1/forecast.json?KEY=%s&q=%s&days=2'
    actual_url = baseurl % (key, zipcode)
    data = dict()
    try:
        result = urllib2.urlopen(actual_url).read()
        data = json.loads(result)
    except:
        print(traceback.format_exc())
    return data


def generate_weather_string(data):
    tomorrow = data['forecast']['forecastday'][1]
    return "The weather condition will be %s in %s on %s. The temperature will be %s to %s F (%s to %s C)." % (
        tomorrow['day']['condition']['text'],
        data['location']['name'],
        datetime.fromtimestamp(tomorrow['date_epoch']).strftime('%m/%d/%Y'),
        # tomorrow['date'],
        tomorrow['day']['mintemp_f'],
        tomorrow['day']['maxtemp_f'],
        tomorrow['day']['mintemp_c'],
        tomorrow['day']['maxtemp_c'],
    )


def test_email(request):
    user_id = None
    if request.user.is_authenticated():
        user_id = request.user.id
    else:
        return HttpResponseRedirect("/accounts/login/")
    reminders = Reminder.objects.filter(user_id=user_id)
    # De-duplicate zipcode.
    zipcodes = set()
    for reminder in reminders:
        zipcodes.add(reminder.zipcode)
    body = "Dear %s,\n\n" % request.user.username
    for zipcode in zipcodes:
        body += generate_weather_string(get_weather(zipcode)) + "\n"
    body += "\nBest,\nWeather Reminder"
    message = EmailMessage("Weather Report", body, to=[request.user.email])
    message.send()
    return HttpResponseRedirect("/")


def secret_trigger(request):
    reminders = Reminder.objects.all()
    zip_reminders_map = defaultdict(list)
    # Aggregate by zipcode
    for reminder in reminders:
        zip_reminders_map[reminder.zipcode].append(reminder)
    # Aggregate by user email
    emails = defaultdict(dict)
    for zipcode in zip_reminders_map:
        warnings = generate_warnings(get_weather(zipcode))
        reminder_list = zip_reminders_map[zipcode]
        for reminder in reminder_list:
            if reminder.warning_event in warnings.keys():
                emails[(reminder.user.username, reminder.user.email)][zipcode] = warnings[reminder.warning_event]
                reminder.reminder_sent = datetime.now()
                reminder.save()
    response = {'emails_sent': []}
    for user_id, email in emails:
        body = "Dear %s,\n\n" % user_id
        for zipcode in emails[(user_id, email)]:
            body += emails[(user_id, email)][zipcode] + "\n"
        body += "\n Best,\nWeather Reminder"
        message = EmailMessage("Weather Reminder", body, to=[email])
        message.send()
        response['emails_sent'].append(email)
    return HttpResponse(json.dumps(response))


def generate_warnings(data):
    warnings = dict()
    try:
        today_weather = data['forecast']['forecastday'][0]['day']
        tomorrow_weather = data['forecast']['forecastday'][1]['day']
        RAIN_CODES = (1087,
                      1072, 1150, 1153, 1168, 1171,
                      1063, 1180, 1183, 1186, 1189, 1192, 1195, 1198, 1201, 1240, 1243, 1246, 1273, 1276,
                      1261, 1264)
        SNOW_CODES = (1066, 1114, 1210, 1213, 1216, 1219, 1222, 1225, 1255, 1258, 1279, 1282,
                      1069, 1204, 1207, 1249, 1252,
                      1117)
        warning_text = generate_weather_string(data)
        warnings[Reminder.ALWAYS] = warning_text
        if tomorrow_weather['condition']['code'] in RAIN_CODES:
            warnings[
                Reminder.RAIN] = warning_text + " It will be raining tomorrow, please remember to take your umbrella."
        if tomorrow_weather['condition']['code'] in SNOW_CODES:
            warnings[Reminder.SNOW] = warning_text + " It will be snowing tomorrow, please drive carefully."
        if (float(tomorrow_weather['mintemp_f']) - float(today_weather['mintemp_f']) <= -3 or
                        float(tomorrow_weather['maxtemp_f']) - float(today_weather['maxtemp_f']) <= -3):
            warnings[
                Reminder.TEMPDROP3F] = warning_text + " The temperature will drop by more than 3 F, please wear warmer clothes."
        if (float(tomorrow_weather['mintemp_f']) - float(today_weather['mintemp_f']) >= 3 or
                        float(tomorrow_weather['maxtemp_f']) - float(today_weather['maxtemp_f']) >= 3):
            warnings[Reminder.TEMPRISE3F] = warning_text + " The temperature will rise by more than 3 F."
    except:
        print(traceback.format_exc())
    return warnings
