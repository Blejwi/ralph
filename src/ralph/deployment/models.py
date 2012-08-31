#!/usr/bin/env python
# -*- coding: utf-8 -*-

from __future__ import absolute_import
from __future__ import division
from __future__ import print_function
from __future__ import unicode_literals

import os
import unicodedata

from django.conf import settings
from django.db import models as db
from django.dispatch.dispatcher import Signal
from django.dispatch import receiver
from django.utils.translation import ugettext_lazy as _
from dj.choices import Choices
from dj.choices.fields import ChoiceField
from lck.django.common.models import MACAddressField, Named, TimeTrackable

from ralph.cmdb.models import CI
from ralph.cmdb.models_audits import Auditable, create_issue
from ralph.cmdb.models_common import getfunc
from ralph.discovery.models import Device


# This signal is fired, when deployment is accepted in Bugtracker.
# note, that you should manually change deployment statuses.
deployment_accepted = Signal(providing_args=['deployment_id'])


def normalize_owner(owner):
    owner = owner.name.lower().replace(' ', '.')
    return unicodedata.normalize('NFD', owner).encode('ascii', 'ignore')


def get_technical_owner(device):
    owners = device.venture.technical_owners()
    return normalize_owner(owners[0]) if owners else None


def get_business_owner(device):
    owners = device.venture.business_owners()
    return normalize_owner(owners[0]) if owners else None


class DeploymentStatus(Choices):
    _ = Choices.Choice

    open = _('open')
    in_progress = _('in progress')
    in_deployment = _('in deployment')
    resolved_fixed = _('resolved fixed')


class FileType(Choices):
    _ = Choices.Choice

    LINUX = Choices.Group(0)
    kernel = _("kernel")
    initrd = _("initrd")

    CONFIGURATION = Choices.Group(40)
    boot_ipxe = _("boot_ipxe")
    kickstart = _("kickstart")

    OTHER = Choices.Group(100)
    other = _("other")


def preboot_file_name(instance, filename):
    return os.sep.join(('pxe', instance.get_ftype_display(), instance.name))


class PrebootFile(Named):
    ftype = ChoiceField(verbose_name=_("file type"), choices=FileType,
        default=FileType.other)
    raw_config = db.TextField(verbose_name=_("raw config"), blank=True)
    file = db.FileField(verbose_name=_("file"), upload_to=preboot_file_name,
        null=True, blank=True, default=None)

    class Meta:
        verbose_name = _("preboot file")
        verbose_name_plural = _("preboot files")

    def get_filesize_display(self):
        template = """binary {size:.2f} MB"""
        return template.format(
            size=self.file.size/1024/1024,
        )


class Preboot(Named, TimeTrackable):
    files = db.ManyToManyField(PrebootFile, null=True, blank=True,
        verbose_name=_("files"))

    class Meta:
        verbose_name = _("preboot")
        verbose_name_plural = _("preboots")


class Deployment(Auditable):
    device = db.ForeignKey(Device)
    mac =  MACAddressField()
    status = db.IntegerField(choices=DeploymentStatus(),
        default=DeploymentStatus.open.id)
    ip = db.IPAddressField(verbose_name=_("IP address"))
    hostname = db.CharField(verbose_name=_("hostname"), max_length=255,
        unique=True)
    preboot = db.ForeignKey(Preboot, verbose_name=_("preboot"), null=True,
        on_delete=db.SET_NULL)
    venture = db.ForeignKey('business.Venture', verbose_name=_("venture"),
        null=True, on_delete=db.SET_NULL)
    venture_role = db.ForeignKey('business.VentureRole', null=True,
        verbose_name=_("role"), on_delete=db.SET_NULL)
    done_plugins = db.TextField(verbose_name=_("done plugins"),
        blank=True, default='')
    is_running = db.BooleanField(verbose_name=_("is running"),
        default=False) # a database-level lock for deployment-related tasks
    puppet_certificate_revoked = db.BooleanField(default=False)

    class Meta:
        verbose_name = _("deployment")
        verbose_name_plural = _("deployments")

    def fire_issue(self):
        s = settings.ISSUETRACKERS['default']['OPA']
        ci = None
        bowner = get_business_owner(self.device)
        towner = get_technical_owner(self.device)
        params = dict(
            ci_uid = CI.get_uid_by_content_object(self.device),
            # FIXME: doesn't check if CI even exists
            description = 'Please accept',
            summary = 'Summary',
            ci=ci,
            technical_assigne=towner,
            business_assignee=bowner,
            template=s['TEMPLATE'],
            issue_type=s['ISSUETYPE'],
        )
        getfunc(create_issue)(type(self), self.id, params)


class DeploymentPoll(db.Model):
    key = db.CharField(max_length=255)
    date = db.DateTimeField()
    checked = db.BooleanField(default=False)


@receiver(deployment_accepted, dispatch_uid='ralph.cmdb.deployment_accepted')
def handle_deployment_accepted(sender, deployment_id, **kwargs):
    # sample deployment accepted signal code.
    pass


# Import all the plugins
import ralph.deployment.plugins
