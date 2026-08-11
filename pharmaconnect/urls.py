"""
URL configuration for pharmaconnect project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/6.0/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.contrib import admin
from django.urls import include, path

from pharmaconnect.views import service_worker, manifest

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', include('accounts.urls')),
    path('patients/', include('patients.urls', namespace='patients')),
    path('pharmacies/', include('pharmacies.urls', namespace='pharmacies')),
    path('grossistes/', include('wholesalers.urls', namespace='wholesalers')),
    path('anticounterfeit/', include('anticounterfeit.urls', namespace='anticounterfeit')),
    path('orders/', include('orders.urls', namespace='orders')),

    # PWA : servis à la racine pour couvrir tout le site (voir pharmaconnect/views.py)
    path('sw.js', service_worker, name='sw.js'),
    path('manifest.json', manifest, name='manifest'),
]