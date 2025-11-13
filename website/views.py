from django.shortcuts import render, get_object_or_404, redirect
from django.db.models import Q
from django.contrib import messages
from django.utils.translation import gettext as _
#for robots.txt
from django.http import HttpResponse
from django.urls import reverse


from django.core.paginator import Paginator, PageNotAnInteger, EmptyPage

from .models import BlogPost, Comment, Product, Category, Tag


def home(request):
    latest_posts = BlogPost.objects.filter(is_published=True).order_by("-published_at")[:3]
    featured_products = Product.objects.filter(is_active=True)[:3]

    return render(request, "website/home.html", {
        "latest_posts": latest_posts,
        "featured_products": featured_products,
    })


def about(request):
    return render(request, "website/about.html")


def lab(request):
    return render(request, "website/lab.html")


def blog_list(request, category_slug=None):
    q = request.GET.get("q", "").strip()

    posts_qs = BlogPost.objects.filter(is_published=True)
    categories = Category.objects.all()
    current_category = None

    if category_slug:
        current_category = Category.objects.filter(slug=category_slug).first()
        if current_category:
            posts_qs = posts_qs.filter(categories=current_category)

    if q:
        posts_qs = posts_qs.filter(
            Q(title_ar__icontains=q) |
            Q(title_en__icontains=q) |
            Q(body_ar__icontains=q) |
            Q(body_en__icontains=q)
        )

    paginator = Paginator(posts_qs, 5)
    page = request.GET.get("page", 1)

    try:
        page_obj = paginator.page(page)
    except PageNotAnInteger:
        page_obj = paginator.page(1)
    except EmptyPage:
        page_obj = paginator.page(paginator.num_pages)

    return render(request, "website/blog_list.html", {
        "posts": page_obj.object_list,
        "page_obj": page_obj,
        "paginator": paginator,
        "categories": categories,
        "current_category": current_category,
        "q": q,
    })


def blog_detail(request, slug):
    post = get_object_or_404(BlogPost, slug=slug, is_published=True)
    comments = post.comments.filter(is_approved=True).order_by("created_at")

    og_image_url = None
    if post.thumbnail:
        og_image_url = request.build_absolute_uri(post.thumbnail.url)

    if request.method == "POST":
        name = request.POST.get("name", "").strip()
        email = request.POST.get("email", "").strip()
        content = request.POST.get("content", "").strip()

        if name and content:
            Comment.objects.create(
                post=post,
                name=name,
                email=email or None,
                content=content,
                is_approved=True,
            )
            messages.success(request, _("تم إضافة تعليقك بنجاح."))
            return redirect("blog_detail", slug=post.slug)
        else:
            messages.error(request, _("الاسم والمحتوى مطلوبان."))

    return render(request, "website/blog_detail.html", {
        "post": post,
        "comments": comments,
        "og_image_url": og_image_url,
    })



def product_list(request):
    products = Product.objects.filter(is_active=True).order_by("name_ar")
    return render(request, "website/product_list.html", {
        "products": products,
    })


def product_detail(request, slug):
    product = get_object_or_404(Product, slug=slug, is_active=True)
    return render(request, "website/product_detail.html", {
        "product": product,
    })


def contact(request):
    if request.method == "POST":
        name = request.POST.get("name", "").strip()
        email = request.POST.get("email", "").strip()
        subject = request.POST.get("subject", "").strip()
        message_body = request.POST.get("message", "").strip()

        # هنا فقط نعرض رسالة نجاح، لاحقاً ممكن نربطها بإرسال بريد
        if name and message_body:
            messages.success(request, _("تم إرسال رسالتك، سنعاود التواصل معك قريباً."))
            return redirect("contact")

    return render(request, "website/contact.html")


def blog_tag(request, tag_slug):
    q = request.GET.get("q", "").strip()

    posts_qs = BlogPost.objects.filter(is_published=True)
    categories = Category.objects.all()
    current_category = None

    current_tag = Tag.objects.filter(slug=tag_slug).first()
    if current_tag:
        posts_qs = posts_qs.filter(tags=current_tag)

    if q:
        posts_qs = posts_qs.filter(
            Q(title_ar__icontains=q) |
            Q(title_en__icontains=q) |
            Q(body_ar__icontains=q) |
            Q(body_en__icontains=q)
        )

    paginator = Paginator(posts_qs, 5)
    page = request.GET.get("page", 1)

    try:
        page_obj = paginator.page(page)
    except PageNotAnInteger:
        page_obj = paginator.page(1)
    except EmptyPage:
        page_obj = paginator.page(paginator.num_pages)

    return render(request, "website/blog_list.html", {
        "posts": page_obj.object_list,
        "page_obj": page_obj,
        "paginator": paginator,
        "categories": categories,
        "current_category": current_category,
        "current_tag": current_tag,
        "q": q,
    })

def robots_txt(request):
    lines = [
        "User-agent: *",
        "Disallow: /admin/",
        "",
        # نخلي جوجل يعرف مكان السايت ماب
        f"Sitemap: {request.build_absolute_uri(reverse('sitemap'))}",
        "",
    ]
    text = "\n".join(lines)
    return HttpResponse(text, content_type="text/plain")

