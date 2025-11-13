# accounting/views.py

from django.http import HttpResponse

def ping(request):
    return HttpResponse("Accounting app is alive.")
