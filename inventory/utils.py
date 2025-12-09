# inventory/utils.py

from django.template.loader import render_to_string
from django.http import HttpResponse
from weasyprint import HTML, CSS
from django.conf import settings


def render_pdf_view(request, template_path, context, filename="document.pdf"):
    """
    دالة مساعدة لتحويل قالب HTML إلى استجابة PDF.
    """
    # 1. تحويل القالب إلى نص HTML
    html_string = render_to_string(template_path, context, request=request)

    # 2. إعداد المسار الأساسي للملفات الثابتة (CSS/Images)
    # WeasyPrint يحتاج لرابط كامل (http://...) أو مسار ملف لجلب الصور
    base_url = request.build_absolute_uri("/")

    # 3. توليد PDF
    html = HTML(string=html_string, base_url=base_url)

    # تحسين الخطوط العربية (اختياري، يفضل تحميل الخط في القالب)
    pdf_file = html.write_pdf(stylesheets=[
        # يمكن إضافة ملف CSS خارجي هنا إذا لزم الأمر
        # CSS(settings.STATIC_ROOT + '/css/pdf_style.css')
    ])

    # 4. إرجاع الاستجابة (Browser Response)
    response = HttpResponse(pdf_file, content_type='application/pdf')

    # 'inline' = عرض في المتصفح | 'attachment' = تحميل مباشر
    response['Content-Disposition'] = f'inline; filename="{filename}"'

    return response