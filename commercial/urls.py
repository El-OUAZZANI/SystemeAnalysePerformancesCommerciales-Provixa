# commercial/urls.py
from django.urls import path
from . import views

app_name = 'commercial'

urlpatterns = [
    path('', views.vue_connexion, name='accueil'),
    path('connexion/', views.vue_connexion, name='connexion'),
    path('deconnexion/', views.vue_deconnexion, name='deconnexion'),

    path('chef-region/dashboard/', views.dashboard_chef_region, name='dashboard_chef_region'),
    path('chef-region/dashboard/data/', views.dashboard_chef_region_data, name='dashboard_chef_region_data'),
    path('chef-region/vendeurs/', views.liste_vendeurs_chef_region, name='liste_vendeurs_chef_region'),
    path('chef-region/produits/', views.liste_produits_chef_region, name='produits_chef_region'),
    path('chef-region/parametres/', views.parametres_chef_region, name='parametres_chef_region'),
    path('chef-region/analyses/', views.analyses_chef_region, name='analyses_chef_region'),

    path('commercial/vue-ensemble/', views.vue_ensemble_commercial, name='vue_ensemble_commercial'),
    path('commercial/agence/<str:id_agence>/', views.dashboard_agence_commercial, name='dashboard_agence_commercial'),
    path('commercial/agence/<str:id_agence>/data/', views.dashboard_agence_commercial_data, name='dashboard_agence_commercial_data'),
    path('commercial/agence/<str:id_agence>/vendeurs/', views.vendeurs_agence_commercial, name='vendeurs_agence_commercial'),
    path('commercial/agence/<str:id_agence>/produits/', views.produits_agence_commercial, name='produits_agence_commercial'),
    path('commercial/agence/<str:id_agence>/previsions/', views.previsions_agence_commercial, name='previsions_agence_commercial'),
    path('commercial/parametres/', views.parametres_commercial, name='parametres_commercial'),
]