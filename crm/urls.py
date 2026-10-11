from django.urls import path

from . import views

app_name = "crm"

urlpatterns = [
    path("", views.overview, name="overview"),
    path("opportunities/board/", views.board, name="board"),
    path("opportunities/<int:pk>/stage/", views.opportunity_stage, name="opportunity_stage"),
    path("leads/<int:pk>/", views.lead, name="lead"),
    path("leads/<int:pk>/convert/", views.lead_convert, name="lead_convert"),
    path("opportunities/<int:pk>/", views.opportunity, name="opportunity"),
    path("proposals/<int:pk>/", views.proposal, name="proposal"),
    path("proposals/<int:pk>/action/", views.proposal_action, name="proposal_action"),
    path("contracts/<int:pk>/", views.contract, name="contract"),
    path("share/<str:kind>/<int:pk>/", views.share, name="share"),
    path("p/<str:token>/", views.public, name="public"),
    path("reviews/", views.reviews, name="reviews"),
    path("reviews/request/", views.review_request, name="review_request"),
    path("r/<str:token>/", views.review_public, name="review_public"),
    path("tasks/<int:pk>/done/", views.task_done, name="task_done"),
    path("calendar/", views.calendar, name="calendar"),
    path("<str:kind>/", views.crm_list, name="list"),
    path("<str:kind>/new/", views.crm_new, name="new"),
    path("<str:kind>/<int:pk>/edit/", views.crm_edit, name="edit"),
]
