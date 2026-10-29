from sqlalchemy.orm import Session

from .models import AuditLog, User


def record(db: Session, actor: User | None, action: str, entity: str,
           entity_id=None, before=None, after=None, reason=None) -> None:
    db.add(AuditLog(actor_id=actor.id if actor else None, action=action, entity=entity,
                    entity_id=str(entity_id) if entity_id is not None else None,
                    before=before, after=after, reason=reason))
