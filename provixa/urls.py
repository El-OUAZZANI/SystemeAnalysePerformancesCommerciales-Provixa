from django.urls import path, include
from django.contrib import admin
urlpatterns = [
    path('admin/', admin.site.urls),
    path('', include('commercial.urls')),  # ← relie tes nouvelles routes
]