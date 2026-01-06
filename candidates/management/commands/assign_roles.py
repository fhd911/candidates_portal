from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError
from django.contrib.auth import get_user_model
from django.db import transaction

from candidates.models import MemberProfile, Opportunity, Committee

User = get_user_model()


class Command(BaseCommand):
    help = "Assign roles to users and auto-link opportunity/committee."

    def add_arguments(self, parser):
        parser.add_argument("--opportunity", type=str, default="", help="Opportunity title (optional).")
        parser.add_argument("--committee", type=str, default="", help="Committee name for MEMBER/CHAIR (required for them).")

        # supervisor
        parser.add_argument("--supervisors", nargs="*", default=[], help="Usernames to set as SUPERVISOR")

        # chair
        parser.add_argument("--chairs", nargs="*", default=[], help="Usernames to set as CHAIR")

        # member
        parser.add_argument("--members", nargs="*", default=[], help="Usernames to set as MEMBER")

        # admin
        parser.add_argument("--admins", nargs="*", default=[], help="Usernames to set as ADMIN")

        parser.add_argument("--activate", action="store_true", help="Set is_active=True for assigned profiles.")
        parser.add_argument("--dry-run", action="store_true", help="Print what would happen without saving.")

    def handle(self, *args, **opts):
        opp_title = (opts["opportunity"] or "").strip()
        committee_name = (opts["committee"] or "").strip()

        supervisors = list(opts["supervisors"] or [])
        chairs = list(opts["chairs"] or [])
        members = list(opts["members"] or [])
        admins = list(opts["admins"] or [])

        activate = bool(opts["activate"])
        dry_run = bool(opts["dry_run"])

        if (chairs or members) and not committee_name:
            raise CommandError("--committee is required when assigning --chairs or --members")

        # Resolve / create active opportunity
        opp = Opportunity.objects.filter(is_active=True).first()
        if not opp:
            if not opp_title:
                opp_title = "فرصة افتراضية"
            if dry_run:
                self.stdout.write(self.style.WARNING(f"[DRY] Would create active Opportunity: {opp_title}"))
                opp = None
            else:
                opp = Opportunity.objects.create(title=opp_title, is_active=True)

        # Resolve / create committee if needed
        com = None
        if committee_name:
            com_qs = Committee.objects.filter(name=committee_name)
            if opp:
                com_qs = com_qs.filter(opportunity=opp)
            com = com_qs.first()

            if not com:
                if dry_run:
                    self.stdout.write(self.style.WARNING(f"[DRY] Would create Committee: {committee_name}"))
                    com = None
                else:
                    if not opp:
                        raise CommandError("No active opportunity available to create committee.")
                    com = Committee.objects.create(opportunity=opp, name=committee_name, is_open=True)

        def get_or_create_profile(u: User):
            p = getattr(u, "profile", None)
            if p:
                return p
            if dry_run:
                self.stdout.write(self.style.WARNING(f"[DRY] Would create MemberProfile for user={u.username}"))
                return None
            return MemberProfile.objects.create(
                user=u,
                is_active=False,
                role=MemberProfile.ROLE_MEMBER,
            )

        def assign(u: User, role: str):
            p = get_or_create_profile(u)

            # print plan
            link_info = ""
            if role == MemberProfile.ROLE_SUPERVISOR:
                link_info = f"opportunity={getattr(opp, 'id', None)}"
            elif role in (MemberProfile.ROLE_MEMBER, MemberProfile.ROLE_CHAIR):
                link_info = f"committee={getattr(com, 'id', None)}"
            elif role == MemberProfile.ROLE_ADMIN:
                link_info = f"opportunity={getattr(opp, 'id', None)}"

            if dry_run:
                self.stdout.write(f"[DRY] {u.username}: role={role}, activate={activate}, {link_info}")
                return

            if not p:
                p = MemberProfile.objects.get(user=u)

            p.role = role
            if activate:
                p.is_active = True

            # clear old links safely
            if hasattr(p, "committee_id"):
                p.committee = None
            if hasattr(p, "opportunity_id"):
                p.opportunity = None

            if role == MemberProfile.ROLE_SUPERVISOR:
                if not hasattr(p, "opportunity_id"):
                    raise CommandError("MemberProfile has no opportunity field.")
                p.opportunity = opp

            elif role in (MemberProfile.ROLE_MEMBER, MemberProfile.ROLE_CHAIR):
                if not hasattr(p, "committee_id"):
                    raise CommandError("MemberProfile has no committee field.")
                p.committee = com

            elif role == MemberProfile.ROLE_ADMIN:
                # Admin: اربطه بالفرصة إن كان الحقل موجود
                if hasattr(p, "opportunity_id"):
                    p.opportunity = opp

            p.save()

        def fetch_users(usernames: list[str]) -> list[User]:
            if not usernames:
                return []
            found = list(User.objects.filter(username__in=usernames))
            missing = sorted(set(usernames) - {u.username for u in found})
            if missing:
                raise CommandError(f"Users not found: {', '.join(missing)}")
            return found

        # Execute assignments
        with transaction.atomic():
            for u in fetch_users(supervisors):
                assign(u, MemberProfile.ROLE_SUPERVISOR)

            for u in fetch_users(chairs):
                assign(u, MemberProfile.ROLE_CHAIR)

            for u in fetch_users(members):
                assign(u, MemberProfile.ROLE_MEMBER)

            for u in fetch_users(admins):
                assign(u, MemberProfile.ROLE_ADMIN)

            if dry_run:
                # rollback intentional
                transaction.set_rollback(True)

        self.stdout.write(self.style.SUCCESS("Done."))
