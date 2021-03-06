#!/usr/bin/env python
# Copyright (C) 2015 Shea G Craig
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.


from distutils.version import LooseVersion
from operator import itemgetter
import os
import sys
import textwrap

import cruftmoji
from repo import Repo
from robo_print import robo_print, LogLevel
import sys
import tools
import FoundationPlist


IGNORED_FILES = ('.DS_Store',)


class Report(object):
    """Encapsulates behavior of a Spruce Report.

    Attributes:
        name: String name for report.
        items_key: Iterable of Tuples specifying output sorting.
            key (str): Key to sort by.
            reverse (bool): Whether to reverse sort.
        items_order: A list of item key names defining their print output
            order.
        metadata_order: A list of metadata key names defining their print
            output order.
    """
    name = "Report"
    description = ""
    items_keys = []
    items_order = []
    metadata_order = []
    separator = "-" * 20

    def __init__(self, repo_data):
        self.items = []
        self.metadata = []
        self.run_report(repo_data)

    def __str__(self):
        return "{}: {}".format(self.__class__, self.name)

    def run_report(self, repo_data):
        pass

    def print_report(self):
        print "{0} {1}{0} :".format(cruftmoji.SPRUCE, self.name)
        if self.description:
            tab = "\t"
            wrapper = textwrap.TextWrapper(
                width=73, initial_indent=tab, subsequent_indent=tab)
            print "\n".join(wrapper.wrap(self.description))
            print
        if self.items or self.metadata:
            if self.items_keys:
                for key, reverse in reversed(self.items_keys):
                    if key == "version":
                        self.items.sort(key=lambda v: LooseVersion(v[key]),
                                        reverse=reverse)
                    else:
                        self.items.sort(key=itemgetter(key), reverse=reverse)
            self._print_section("items")
            self._print_section("metadata")
        else:
            print "\tNo items."
            print

    def _print_section(self, property):
        section = getattr(self, property)
        if len(section) > 0:
            print "\t{}:".format(property.title())
            print "\t" + self.separator
            for item in section:
                order = getattr(self, property + "_order")
                for key in order:
                    print "\t{}: {}".format(key, item[key])
                for key in item:
                    if not key in order:
                        print "\t{}: {}".format(key, item[key])
                print "\t" + self.separator
            print

    def as_dict(self):
        return {"items": self.items, "metadata": self.metadata}


class OutOfDateReport(Report):
    name = "Out of Date Items Report"
    description = ("This report collects all items which are in the "
                   "production catalog, but are not the current "
                   "release version. Items that have dependencies to "
                   "current releases through either the `requires` or "
                   "`update_for` keys are excluded. Items in non-production "
                   "catalogs are also excluded from consideration by this "
                   "report.")
    items_keys = (("name", False), ("version", True))
    items_order = ["name", "path"]

    def __init__(self, repo_data, num_to_save=1):
        self.items = []
        self.metadata = []
        self.num_to_save = num_to_save
        self.run_report(repo_data)

    def run_report(self, repo_data):
        # all_applications = set(version for app in
        #                        repo_data["repo_data"].applications.values() for
        #                        version in app)
        used_items  = repo_data["repo_data"].get_used_items(
            repo_data["manifest_items"], sys.maxint, ("production",))
        current_items = repo_data["repo_data"].get_used_items(
            repo_data["manifest_items"], self.num_to_save, ("production",))
        out_of_date = used_items - current_items
        for item in out_of_date:
            self.items.append(
                {"name": item.name,
                "version": item.version,
                "path": item.pkginfo_path,
                "size": item._human_readable_size()})


class PathIssuesReport(Report):
    name = "Case-Sensitive Path Issues Report"
    description = (
        "This report collects all items whose installer item is referenced "
        "incorrectly due to case-sensitivity errors. Current macOS default "
        "filesystem settings are case-insensitive, yet many admins host Munki "
        "with Linux, which is by default case-sensitive. This can lead to "
        "`installer_item_location` values which work on macOS, but do not "
        "resolve correctly on case sensitive filesystems.")
    items_keys = (("name", False),)
    items_order = ["name", "path"]

    def run_report(self, repo_data):
        pkgs = os.path.join(repo_data["munki_repo"], "pkgs")
        for pkginfo, data in repo_data["pkgsinfo"].items():
            installer = data.get("installer_item_location")
            if installer:
                bad_dirs = self.get_bad_path(installer, pkgs)
                if bad_dirs:
                    result = {"name": data.get("name"),
                              "path": pkginfo,
                              "bad_path_component": bad_dirs}
                    self.items.append(result)

    def get_bad_path(self, installer, path):
        if "/" in installer:
            subdir = installer.split("/")[0]
            if subdir in os.listdir(path):
                return self.get_bad_path(installer.split("/", 1)[1],
                                         os.path.join(path, subdir))
            else:
                return subdir
        else:
            return installer if installer not in os.listdir(path) else None


class MissingInstallerReport(Report):
    name = "Missing Installer Report"
    description = (
        "This report collects all items which refer to nonexistent "
        "installers (`installer_item_location`).")
    items_keys = (("name", False),)
    items_order = ["name", "path"]

    def run_report(self, repo_data):
        pkgs = os.path.join(repo_data["munki_repo"], "pkgs")
        for pkginfo, data in repo_data["pkgsinfo"].items():
            installer = data.get("installer_item_location")
            if installer:
                installer_path = os.path.join(pkgs, installer)
                if not os.path.exists(installer_path):
                    result = {"name": data.get("name"),
                              "path": pkginfo,
                              "missing_installer": installer_path}
                    self.items.append(result)


class OrphanedInstallerReport(Report):
    name = "Orphaned Installer Report"
    description = ("This report collects all pkgs present in the repo which "
                   "are not referenced by any pkginfo files.")

    items_keys = (("path", False),)
    items_order = ["path"]

    def run_report(self, repo_data):
        search_key = "installer_item_location"
        # TODO: join full path
        used_packages = {pkginfo[search_key] for pkginfo in
                         repo_data["pkgsinfo"].values() if search_key in
                         pkginfo}
        pkgs_dir = os.path.join(repo_data["munki_repo"], "pkgs")
        bundle_packages = set()
        for dirpath, _, filenames in os.walk(pkgs_dir):
            if any(bundle_pkg in dirpath for bundle_pkg in bundle_packages):
                # Contents of a bundle.
                continue
            elif os.path.splitext(dirpath)[1].upper() in (".PKG", ".MPKG"):
                # This is a non-flat package. Check for the dirname only,
                # then move on to the next iteration.
                if dirpath not in used_packages:
                    self.items.append({"path": dirpath})
                    bundle_packages.add(dirpath)
                continue
            rel_path = dirpath.split(pkgs_dir)[1]
            for filename in filenames:
                # Slice off preceding slash.
                rel_filename = os.path.join(rel_path, filename)
                rel_filename = (rel_filename[1:] if
                                rel_filename.startswith("/") else rel_filename)
                if rel_filename not in used_packages:
                    item_path = os.path.join(dirpath, filename)
                    # result = {"name": item_path, "path": item_path}
                    result = {"path": item_path}
                    self.items.append(result)


class NoUsageReport(Report):
    name = "Unused Item Report"
    description = ("This report collects all items in the catalogs which are "
                   "not used in any manifests, are not required by any items "
                   "that are in use (using the `requires` key), nor are "
                   "updates for an item in use (using the `update_for` key.")
    items_keys = (("name", False), ("version", True))
    items_order = ["name", "path"]

    def run_report(self, repo_data):
        all_applications = set(version for app in
                               repo_data["repo_data"].applications.values() for
                               version in app)
        num_to_keep = sys.maxint
        used_items  = repo_data["repo_data"].get_used_items(
            repo_data["manifest_items"], num_to_keep)
        unused = all_applications - used_items
        for item in unused:
            # TODO: Temporary attempt at stopping plist exception
            self.items.append(
                {"name": item.name,
                "version": item.version,
                "path": item.pkg_path or "",
                "size": item._human_readable_size()})


class PkgsinfoWithErrorsReport(Report):
    name = "Pkginfo Syntax Error Report"
    description = ("This report collects all items which have invalid plist "
                   "syntax in their pkginfo file.")
    items_keys = (("path", False),)
    items_order = ["path"]

    def run_report(self, errors):
        for key, value in errors.items():
            self.items.append({"path": key, "error": value})


# TODO: Add to other reports.
class UnusedDiskUsageReport(Report):
    name = "Unused / Out Of Date Item Disk Usage"

    def run_report(self, cache):
        unused_size = 0.0
        for item in cache["unused_items"]:
            pkginfo = cache["pkgsinfo"][item["path"]]
            size = pkginfo.get("installer_item_size")
            if size:
                unused_size += size

        # Munki sizes are in kilobytes, so convert to true GIGA!
        self.metadata.append(
            {"Unused files account for": "{:,.2f} gigabytes".format(
                unused_size / (1024 ** 2))})


class SimpleConditionReport(Report):
    """Report Subclass for simple reports."""
    items_keys = (("name", False), ("version", True))
    items_order = ["name", "path"]
    conditions = []

    def run_report(self, repo_data):
        self.items = self.get_info(self.conditions, repo_data["pkgsinfo"])

    def get_info(self, conditions, cache):
        output = []
        for path, pkginfo in cache.items():
            if all(condition(pkginfo) for condition in conditions):
                item = {"name": pkginfo["name"],
                        "version": pkginfo["version"],
                        "path": path}
                output.append(item)
        return sorted(output)


class UnattendedTestingReport(SimpleConditionReport):
    name = "Unattended Installs in Testing Report"
    description = ("This report collects all items in the testing catalogs "
                   "which do not require user-intervention (i.e. use "
                   "the 'unattended_install: True' setting).")
    conditions = (tools.in_testing, tools.is_unattended_install)


class UnattendedProdReport(SimpleConditionReport):
    name = "Attended Installs in Production Report"
    description = ("This report collects all items in the production catalog "
                   "which require user-intervention (i.e. do not use the "
                   "'unattended_install: True' setting).")
    conditions = (tools.in_production, tools.is_not_unattended_install)


class ForceInstallTestingReport(SimpleConditionReport):
    name = "Testing Non-Forced Installation Report"
    description = ("This report collects all items in the testing catalogs "
                   "which do not use the `force_install_after_date` key in "
                   "their pkginfo.")
    conditions = (tools.in_testing,
                  lambda x: x.get("force_install_after_date") is None)


class ForceInstallProdReport(SimpleConditionReport):
    name = "Production Forced Installation Report"
    description = ("This report collects all items in the production catalog "
                   "which use the `force_install_after_date` key in their "
                   "pkginfo.")
    conditions = (tools.in_production,
                  lambda x: x.get("force_install_after_date") is not None)


def run_reports(args):
    expanded_cache, errors = build_expanded_cache()

    # TODO: Add sorting to output or reporting.
    report_results = []

    report_results.append(PathIssuesReport(expanded_cache))
    report_results.append(MissingInstallerReport(expanded_cache))
    report_results.append(OrphanedInstallerReport(expanded_cache))
    report_results.append(PkgsinfoWithErrorsReport(errors))
    report_results.append(OutOfDateReport(expanded_cache))
    report_results.append(NoUsageReport(expanded_cache))
    # Add the results of the last two reports together to determine
    # wasted disk space.
    # expanded_cache["unused_items"] = [item for report in report_results[-2:]
    #                                   for item in report.items]
    # report_results.append(UnusedDiskUsageReport(expanded_cache))
    report_results.append(UnattendedTestingReport(expanded_cache))
    report_results.append(UnattendedProdReport(expanded_cache))
    report_results.append(ForceInstallTestingReport(expanded_cache))
    report_results.append(ForceInstallProdReport(expanded_cache))

    if args.plist:
        dict_reports = {report.name: report.as_dict() for report in
                        report_results}
        print FoundationPlist.writePlistToString(dict_reports)
    else:
        for report in report_results:
            report.print_report()


def build_expanded_cache():
    munki_repo = tools.get_repo_path()

    # Ensure repo is mounted.
    all_path = os.path.join(munki_repo, "catalogs", "all")
    try:
        all_plist = FoundationPlist.readPlist(all_path)
    except FoundationPlist.NSPropertyListSerializationException:
        sys.exit("Please mount your Munki repo and try again.")

    cache, errors = tools.build_pkginfo_cache_with_errors(munki_repo)

    expanded_cache = {}
    expanded_cache["pkgsinfo"] = cache
    expanded_cache["munki_repo"] = munki_repo
    expanded_cache["manifest_items"] = get_manifest_items(
        tools.get_manifests())
    expanded_cache["repo_data"] = Repo(expanded_cache["pkgsinfo"])

    return (expanded_cache, errors)


def get_manifest_items(manifests):
    """Determine all used items.

    First, gets the names of all managed_[un]install, optional_install,
    and managed_update items, including in conditional sections.

    Then looks through those items' pkginfos for 'requires' entries, and
    adds them to the list.

    Finally, it looks through all pkginfos looking for 'update_for'
    items in the used list; if found, that pkginfo's 'name' is added
    to the list.
    """
    collections = ("managed_installs", "managed_uninstalls",
                   "optional_installs", "managed_updates")
    used_items = set()
    for manifest in manifests:
        for collection in collections:
            items = manifests[manifest].get(collection)
            if items:
                used_items.update(items)
        conditionals = manifests[manifest].get("conditional_items", [])
        for conditional in conditionals:
            for collection in collections:
                items = conditional.get(collection)
                if items:
                    used_items.update(items)

    return used_items


def main():
    pass


if __name__ == "__main__":
    main()
