from django.contrib import messages
from django.db.models import Q
from django.http import HttpResponse
from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse
from django.utils.translation import gettext as _

from django.views.generic import TemplateView, ListView, DetailView, View

from .models import BlogPost, Comment, Product, Category, Tag, ContactMessage


# ============================================================
# Home & Static Pages
# ============================================================

class HomeView(TemplateView):
    """
    Public landing page for Mazoon Aluminum.
    Shows latest blog posts and featured products.
    """
    template_name = "website/home.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["latest_posts"] = (
            BlogPost.objects.filter(is_published=True)
            .order_by("-published_at")[:3]
        )
        context["featured_products"] = (
            Product.objects.filter(is_active=True)[:3]
        )
        return context


class AboutView(TemplateView):
    """Static 'About' page."""
    template_name = "website/about.html"


class LabView(TemplateView):
    """Static 'Lab' page."""
    template_name = "website/lab.html"


# ============================================================
# Blog: list, tag, detail
# ============================================================

class BlogListView(ListView):
    """
    Blog list view with optional category filter and search query.
    """
    model = BlogPost
    template_name = "website/blog_list.html"
    context_object_name = "posts"
    paginate_by = 5

    def get_queryset(self):
        q = self.request.GET.get("q", "").strip()
        qs = BlogPost.objects.filter(is_published=True)

        # optional category filter
        category_slug = self.kwargs.get("category_slug")
        self.current_category = None
        if category_slug:
            self.current_category = Category.objects.filter(
                slug=category_slug
            ).first()
            if self.current_category:
                qs = qs.filter(categories=self.current_category)

        if q:
            qs = qs.filter(
                Q(title_ar__icontains=q)
                | Q(title_en__icontains=q)
                | Q(body_ar__icontains=q)
                | Q(body_en__icontains=q)
            )

        self.search_query = q
        return qs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["categories"] = Category.objects.all()
        context["current_category"] = getattr(self, "current_category", None)
        context["q"] = getattr(self, "search_query", "")
        return context


class BlogTagView(ListView):
    """
    Blog list filtered by tag, with search support.
    Uses same template as BlogListView.
    """
    model = BlogPost
    template_name = "website/blog_list.html"
    context_object_name = "posts"
    paginate_by = 5

    def get_queryset(self):
        q = self.request.GET.get("q", "").strip()
        qs = BlogPost.objects.filter(is_published=True)

        self.current_category = None
        tag_slug = self.kwargs.get("tag_slug")
        self.current_tag = Tag.objects.filter(slug=tag_slug).first()
        if self.current_tag:
            qs = qs.filter(tags=self.current_tag)

        if q:
            qs = qs.filter(
                Q(title_ar__icontains=q)
                | Q(title_en__icontains=q)
                | Q(body_ar__icontains=q)
                | Q(body_en__icontains=q)
            )

        self.search_query = q
        return qs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["categories"] = Category.objects.all()
        context["current_category"] = getattr(self, "current_category", None)
        context["current_tag"] = getattr(self, "current_tag", None)
        context["q"] = getattr(self, "search_query", "")
        return context


class BlogDetailView(DetailView):
    """
    Single blog post page with comments and OG image handling.
    """
    model = BlogPost
    template_name = "website/blog_detail.html"
    context_object_name = "post"
    slug_field = "slug"
    slug_url_kwarg = "slug"

    def get_queryset(self):
        return BlogPost.objects.filter(is_published=True)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        post = self.object

        comments = post.comments.filter(is_approved=True).order_by("created_at")
        context["comments"] = comments

        og_image_url = None
        if post.thumbnail:
            og_image_url = self.request.build_absolute_uri(post.thumbnail.url)
        context["og_image_url"] = og_image_url

        return context

    def post(self, request, *args, **kwargs):
        """
        Handle comment form submission.
        """
        self.object = self.get_object()
        post = self.object

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

        messages.error(request, _("الاسم والمحتوى مطلوبان."))
        return self.get(request, *args, **kwargs)


# ============================================================
# Products
# ============================================================

class ProductListView(ListView):
    """
    Public list of active products.
    """
    model = Product
    template_name = "website/product_list.html"
    context_object_name = "products"

    def get_queryset(self):
        return Product.objects.filter(is_active=True).order_by("name_ar")


class ProductDetailView(DetailView):
    """
    Public product detail page.
    """
    model = Product
    template_name = "website/product_detail.html"
    context_object_name = "product"
    slug_field = "slug"
    slug_url_kwarg = "slug"

    def get_queryset(self):
        return Product.objects.filter(is_active=True)


# ============================================================
# Contact
# ============================================================

class ContactView(View):
    """
    Simple contact form view.
    - Saves valid messages to the database.
    - Uses a honeypot field to filter basic bots.
    """
    template_name = "website/contact.html"

    def get(self, request, *args, **kwargs):
        return render(request, self.template_name)

    def post(self, request, *args, **kwargs):
        # Honeypot field: if filled, treat as spam and silently ignore
        honeypot = request.POST.get("website", "").strip()
        if honeypot:
            # Optional: you can log it if you want
            return redirect("contact")

        name = request.POST.get("name", "").strip()
        email = request.POST.get("email", "").strip()
        phone = request.POST.get("phone", "").strip()
        subject = request.POST.get("subject", "").strip()
        message_body = request.POST.get("message", "").strip()

        if not name or not message_body:
            messages.error(request, _("الرجاء تعبئة الاسم والرسالة."))
            return render(request, self.template_name)

        # Save message to database
        ContactMessage.objects.create(
            name=name,
            email=email,
            phone=phone,
            subject=subject,
            message=message_body,
        )

        messages.success(request, _("تم إرسال رسالتك، سنعاود التواصل معك قريباً."))
        return redirect("contact")


# ============================================================
# Robots.txt
# ============================================================

def robots_txt(request):
    """
    Basic robots.txt for search engines.
    """
    lines = [
        "User-agent: *",
        "Disallow: /admin/",
        "",
        f"Sitemap: {request.build_absolute_uri(reverse('sitemap'))}",
        "",
    ]
    text = "\n".join(lines)
    return HttpResponse(text, content_type="text/plain")
