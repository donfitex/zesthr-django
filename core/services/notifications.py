from django.db import transaction

from ..models import Notification


@transaction.atomic
def notify(
    *,
    user,
    notification_type,
    title,
    message,
    url="",
    unique_key=None,
):
    if not user:
        return None

    values = dict(notification_type=notification_type, title=title, message=message, url=url)
    if unique_key:
        notification, _ = Notification.objects.get_or_create(
            recipient=user, unique_key=unique_key, defaults=values)
        return notification
    return Notification.objects.create(recipient=user, unique_key="", **values)



def notify_leave_decision(leave):
    if not leave.emp.user:
        return None

    return notify(
        user=leave.emp.user,
        notification_type=Notification.LEAVE_DECISION,
        title="Leave application updated",
        message=(
            f"Your {leave.get_leave_type_display()} "
            f"request has been "
            f"{leave.get_status_display().lower()}."
        ),
        url="/leaves/",
        unique_key=f"leave:{leave.pk}:{leave.status}",
    )


def notify_pending_leave(leave):
    manager = leave.emp.manager

    if not manager or not manager.user:
        return None

    return notify(
        user=manager.user,
        notification_type=Notification.LEAVE_PENDING,
        title="Leave approval required",
        message=(
            f"{leave.emp.name} submitted "
            f"a leave request."
        ),
        url="/leaves/",
        unique_key=f"leave-pending:{leave.pk}",
    )