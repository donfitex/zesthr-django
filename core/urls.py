from django.contrib.auth import views as auth
from django.contrib.auth.decorators import login_required
from django.urls import path

from . import views as v
from . import views_auth as a

urlpatterns = [
    path("login/", a.LoginView.as_view(), name="login"),
    path("password/change/", login_required(a.PasswordChangeView.as_view()), name="password_change"),
    path("password/reset/", a.PasswordResetView.as_view(), name="password_reset"),
    path("password/reset/sent/", auth.PasswordResetDoneView.as_view(template_name="password_reset_done.html"), name="password_reset_done"),
    path("password/reset/<uidb64>/<token>/", a.PasswordResetConfirmView.as_view(), name="password_reset_confirm"),
    path("password/reset/complete/", auth.PasswordResetCompleteView.as_view(template_name="password_reset_complete.html"), name="password_reset_complete"),
    path("logout/", auth.LogoutView.as_view(), name="logout"),
    path("", v.home, name="home"),
    path("dashboard/", v.dashboard, name="dashboard"),
    path("employees/", v.EmployeeList.as_view(), name="employee_list"),
    path("employees/add/", v.EmployeeCreate.as_view(), name="employee_add"),
    path("employees/<int:pk>/edit/", v.EmployeeUpdate.as_view(), name="employee_edit"),
    path("employees/<int:pk>/delete/", v.EmployeeDelete.as_view(), name="employee_delete"),
    path("employees/<int:pk>/", v.employee_detail, name="employee_detail"),
    path("profile/", v.my_profile, name="my_profile"),
    path("profile/edit/", v.my_profile_edit, name="my_profile_edit"),
    path("employees/<int:pk>/deactivate/", v.employee_deactivate, name="employee_deactivate"),
    path("employees/<int:pk>/reactivate/", v.employee_reactivate, name="employee_reactivate"),
    path("attendance/today/", v.attendance_today, name="attendance_today"),
    path("attendance/", v.AttendanceList.as_view(), name="attendance_list"),
    path("attendance/add/", v.AttendanceCreate.as_view(), name="attendance_add"),
    path("attendance/<int:pk>/edit/", v.AttendanceUpdate.as_view(), name="attendance_edit"),
    path("attendance/<int:pk>/delete/", v.AttendanceDelete.as_view(), name="attendance_delete"),
    path("reports/monthly/", v.monthly_report, name="report"),
    path("payroll/", v.payroll, name="payroll"),
    path("payroll/slip/<int:pk>/", v.slip, name="slip"),
    path("holidays/", v.holidays_list, name="holidays"),
    path("leaves/", v.leaves_list, name="leaves_list"),
    path("leaves/apply/", v.leave_apply, name="leave_apply"),
    path("leaves/<int:pk>/action/", v.leave_action, name="leave_action"),
]
