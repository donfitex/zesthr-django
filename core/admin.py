from django.contrib import admin

from .models import Attendance, Employee, Salary

admin.site.register(Employee)
admin.site.register(Attendance)
admin.site.register(Salary)
