from .models import AttendanceCorrectionRequest, Employee
from .services import corrections


def review_flags(request):
    """Navigation hints: does this user review attendance corrections, and how many are waiting?

    Costs at most two small queries, and only for signed-in users who have an employee profile
    or the HR review permission.
    """
    user = request.user
    if not user.is_authenticated:
        return {}
    profile = getattr(user, "employee_profile", None)
    is_hr = user.has_perm("core.review_attendance_corrections")
    if profile is None and not is_hr:
        return {}
    is_manager = profile is not None and Employee.objects.filter(manager=profile, is_active=True).exists()
    if not (is_hr or is_manager):
        return {}
    pending = corrections.reviewable_requests(user).filter(status=AttendanceCorrectionRequest.PENDING).count()
    return {"is_correction_reviewer": True, "pending_corrections": pending}
