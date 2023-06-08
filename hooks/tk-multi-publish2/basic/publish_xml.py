# Copyright (c) 2017 Shotgun Software Inc.
#
# CONFIDENTIAL AND PROPRIETARY
#
# This work is provided "AS IS" and subject to the Shotgun Pipeline Toolkit
# Source Code License included in this distribution package. See LICENSE.
# By accessing, using, copying or modifying this work you indicate your
# agreement to the Shotgun Pipeline Toolkit Source Code License. All rights
# not expressly granted therein are reserved by Shotgun Software Inc.

import os
import pprint
import tempfile
import uuid
import sys
import sgtk

from tank_vendor import six

HookBaseClass = sgtk.get_hook_baseclass()


class PremiereUploadEDLPlugin(HookBaseClass):
    """
    Plugin for sending photoshop documents to shotgun for review.
    """

    @property
    def icon(self):
        """
        Path to an png icon on disk
        """

        # look for icon one level up from this hook's folder in "icons" folder
        return os.path.join(self.disk_location, os.pardir, "icons", "rendering.png")

    @property
    def name(self):
        """
        One line display name describing the plugin
        """
        return "Upload EDL"

    @property
    def description(self):
        """
        Verbose, multi-line description of what the plugin does. This can
        contain simple html for formatting.
        """
        loader_url = "https://support.shotgunsoftware.com/hc/en-us/articles/219033078"

        return """
                Publishes the EDL file to Shotgun. A <b>Publish</b> entry will be
                created in Shotgun which will include a reference to the file's current
                path on disk. Other users will be able to access the published file via
                the <b><a href='%s'>Loader</a></b> so long as they have access to
                the file's location on disk.

                If the project has not been saved, validation will fail and a button
                will be provided in the logging output to save the file.
                """ % (loader_url,)

    @property
    def settings(self):
        """
        Dictionary defining the settings that this plugin expects to receive
        through the settings parameter in the accept, validate, publish and
        finalize methods.

        A dictionary on the following form::

            {
                "Settings Name": {
                    "type": "settings_type",
                    "default": "default_value",
                    "description": "One line description of the setting"
            }

        The type string should be one of the data types that toolkit accepts as
        part of its environment configuration.
        """
        base_settings = \
            super(PremiereUploadEDLPlugin, self).settings or {}

        # inherit the settings from the base publish plugin
        # settings specific to this class
        premiere_publish_settings = {
            "Publish Template": {
                "type": "template",
                "default": None,
                "description": "Template path for published work files. Should"
                               "correspond to a template defined in "
                               "templates.yml.",
            }
        }

        # update the base settings
        base_settings.update(premiere_publish_settings)

        return base_settings

    @property
    def item_filters(self):
        """
        List of item types that this plugin is interested in.

        Only items matching entries in this list will be presented to the
        accept() method. Strings can contain glob patters such as *, for example
        ["maya.*", "file.maya"]
        """
        return ["premiere.project"]

    def accept(self, settings, item):
        """
        Method called by the publisher to determine if an item is of any
        interest to this plugin. Only items matching the filters defined via the
        item_filters property will be presented to this method.

        A publish task will be generated for each item accepted here. Returns a
        dictionary with the following booleans:

            - accepted: Indicates if the plugin is interested in this value at
               all. Required.
            - enabled: If True, the plugin will be enabled in the UI, otherwise
                it will be disabled. Optional, True by default.
            - visible: If True, the plugin will be visible in the UI, otherwise
                it will be hidden. Optional, True by default.
            - checked: If True, the plugin will be checked in the UI, otherwise
                it will be unchecked. Optional, True by default.

        :param settings: Dictionary of Settings. The keys are strings, matching
            the keys returned in the settings property. The values are `Setting`
            instances.
        :param item: Item to process

        :returns: dictionary with boolean keys accepted, required and enabled
        """
        path = self.parent.engine.project_path

        # if a publish template is configured, disable context change.
        if settings.get("Publish Template").value:
            item.context_change_allowed = False

        if not path:
            # the project has not been saved before (no path determined).
            # provide a save button. the project will need to be saved before
            # validation will succeed.
            self.logger.warn(
                "The Premiere project has not been saved.",
                extra=self.__get_save_as_action()
            )

        self.logger.info(
            "Premiere '%s' plugin accepted." %
            (self.name,)
        )
        return {
            "accepted": True,
            "checked": True
        }

    def validate(self, settings, item):
        """
        Validates the given item to check that it is ok to publish.

        Returns a boolean to indicate validity.

        :param settings: Dictionary of Settings. The keys are strings, matching
            the keys returned in the settings property. The values are `Setting`
            instances.
        :param item: Item to process

        :returns: True if item is valid, False otherwise.
        """
        path = self.parent.engine.project_path

        # ---- ensure the project has been saved

        if not path:
            # the project still requires saving. provide a save button.
            # validation fails.
            error_msg = "The Premiere project '%s' has not been saved." % \
                        (item.name,)
            self.logger.error(
                error_msg,
                extra=self.__get_save_as_action()
            )
            raise ProjectUnsavedError(error_msg)

        # ---- check the project against any attached work template

        # get the path in a normalized state. no trailing separator,
        # separators are appropriate for current os, no double separators,
        # etc.
        path = sgtk.util.ShotgunPath.normalize(path)

        # if the project item has a known work template, see if the path
        # matches. if not, warn the user and provide a way to save the file to
        # a different path
        work_template = item.properties.get("work_template")
        if work_template:
            if not work_template.validate(path):
                self.logger.warning(
                    "The current project does not match the configured work "
                    "template.",
                    extra={
                        "action_button": {
                            "label": "Save File",
                            "tooltip": "Save the current Premiere project"
                                       "to a different file name",
                            # will launch wf2 if configured
                            "callback": self.__get_save_as_action()
                        }
                    }
                )
            else:
                self.logger.debug(
                    "Work template configured and matches project path.")
        else:
            self.logger.debug("No work template configured.")

        # ---- populate the necessary properties and call base class validation

        # populate the publish template on the item if found
        publish_template_setting = settings.get("Publish Template")
        publish_template = self.parent.engine.get_template_by_name(
            publish_template_setting.value)
        if publish_template:
            item.properties["publish_template"] = publish_template

        # set the project path on the item for use by the base plugin
        # validation step. NOTE: this path could change prior to the publish
        # phase.
        item.name = os.path.basename(path)
        item.properties["path"] = path

        # run the base class validation
        return super(PremiereUploadEDLPlugin, self).validate(
            settings, item)

    def publish(self, settings, item):
        """
        Executes the publish logic for the given item and settings.

        :param settings: Dictionary of Settings. The keys are strings, matching
            the keys returned in the settings property. The values are `Setting`
            instances.
        :param item: Item to process
        """
        # populate the publish template on the item if found
        publish_template_setting = settings.get("Publish Template")
        publish_template = self.parent.engine.get_template_by_name(
            publish_template_setting.value)
        if publish_template:
            item.properties["publish_template"] = publish_template

        name = item.name.split('.')[0]
        version = item.name.split('.')[1]
        version = int(re.findall(r'[0-9]{3}', name)[-1])

        template = item.properties['publish_template']
        fields = item.context.as_template_fields(template)
        fields['name'] = name
        fields['version'] = version
        path_to_xml = template.apply_fields(fields)

        self.parent.engine.adobe.app.project.activeSequence.exportAsFinalCutProXML(
            path_to_xml, 1)

        if path_to_xml is None:
            self.logger.error("No render path found")
            return

        # update the item with the saved project path
        item.properties["path"] = path_to_xml
        item.properties["publish_type"] = "Rendered Image"

        # let the base class register the publish
        super(PremiereUploadEDLPlugin, self).publish(settings, item)

        self.logger.info("Publish complete!")

    def finalize(self, settings, item):
        """
        Execute the finalization pass. This pass executes once all the publish
        tasks have completed, and can for example be used to version up files.

        :param settings: Dictionary of Settings. The keys are strings, matching
            the keys returned in the settings property. The values are `Setting`
            instances.
        :param item: Item to process
        """

        # do the base class finalization
        super(PremiereUploadEDLPlugin, self).finalize(settings, item)

    def _get_version_entity(self, item):
        """
        Returns the best entity to link the version to.
        """

        if item.context.entity:
            return item.context.entity
        elif item.context.project:
            return item.context.project
        else:
            return None

    def __get_save_as_action(self):
        """
        Simple helper for returning a log action dict for saving the project
        """

        engine = self.parent.engine

        # default save callback
        callback = lambda: engine.save_as()

        # if workfiles2 is configured, use that for file save
        if "tk-multi-workfiles2" in engine.apps:
            app = engine.apps["tk-multi-workfiles2"]
            if hasattr(app, "show_file_save_dlg"):
                callback = app.show_file_save_dlg

        return {
            "action_button": {
                "label": "Save As...",
                "tooltip": "Save the active project",
                "callback": callback
            }
        }