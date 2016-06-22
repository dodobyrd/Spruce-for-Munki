#!/usr/bin/python
# Copyright 2016 Shea G. Craig
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or
# implied.
#
# See the License for the specific language governing permissions and
# limitations under the License.

"""Remove items from a Munki repo, with the option to relocate them
to a deprecated repository."""


import glob
import os
import shutil
import sys

from munki_tools import FoundationPlist
from munki_tools import tools


NO_CATEGORY = "*NO CATEGORY*"


def main():
    """Do nothing."""
    pass


def deprecate(args):
    """Handle arguments and execute commands."""
    cache = tools.build_pkginfo_cache(tools.get_repo_path())

    removals = get_files_to_remove(args, cache)
    names = get_names_to_remove(removals, cache)

    removal_type = "archived" if args.archive else "removed"
    print_removals(removals, removal_type)
    print_manifest_removals(names)
    warn_about_multiple_refs(removals, cache)

    if not args.force:
        response = raw_input("Are you sure you want to continue? (Y|N): ")
        if response.upper() not in ("Y", "YES"):
            sys.exit()

    if args.archive:
        move_to_archive(removals, args.archive)
    else:
        remove(removals)

    remove_names_from_manifests(names)


def get_files_to_remove(args, cache):
    """Build and return a list of files to remove."""
    removals = []
    # TODO: Refactor
    if args.category:
        removals += get_removals_for_categories(args.category, cache)
    if args.name:
        removals += get_removals_for_names(args.name, cache)
    if args.plist:
        removals += get_removals_from_plist(args.plist, cache)
    return removals


def get_removals_for_categories(categories, cache):
    """Get all pkginfo and pkg files to remove by category."""
    pkginfo_removals = []
    pkg_removals = []
    pkg_prefix = tools.get_pkg_path()
    for path, plist in cache.items():
        if plist.get("category") in categories:
            pkginfo_removals.append(path)
            if plist.get("installer_item_location"):
                pkg_removals.append(
                    os.path.join(pkg_prefix, plist["installer_item_location"]))

    return pkginfo_removals + pkg_removals


def get_removals_for_names(names, cache):
    """Get all pkginfo and pkg files to remove by name."""
    pkginfo_removals = []
    pkg_removals = []
    pkg_prefix = tools.get_pkg_path()
    for path, plist in cache.items():
        if plist.get("name") in names:
            pkginfo_removals.append(path)
            if plist.get("installer_item_location"):
                pkg_removals.append(
                    os.path.join(pkg_prefix, plist["installer_item_location"]))

    return pkginfo_removals + pkg_removals


def get_removals_from_plist(path, cache):
    """Get all pkginfo and pkg files to remove from a plist."""
    data = FoundationPlist.readPlist(path)
    pkg_prefix = tools.get_pkg_path()
    pkg_key = "installer_item_location"
    # Filter out pkginfo files that may already have been removed.
    pkginfo_removals = [item["path"] for item in data.get("removals") if
                        item["path"] in cache]
    pkg_removals = [
        os.path.join(pkg_prefix, cache[pkginfo][pkg_key]) for
        pkginfo in pkginfo_removals if cache[pkginfo].get(pkg_key)]
    return pkginfo_removals + pkg_removals


def get_names_to_remove(removals, cache):
    """Return a set of all the 'name' values for pkginfos to remove."""
    # We only want to remove products from manifests if we are removing
    # ALL of that product.

    # Copy the pkginfo cache. You can't use copy.deepcopy on ObjC
    # objects. So we convert to dict (which copies).
    future_cache = dict(cache)
    # Remove all of the planned removals.
    for removal in removals:
        if removal in future_cache:
            del future_cache[removal]
    # Make a set of all of the remaining names.
    remaining_names = {future_cache[path].get("name") for path in future_cache}
    # Make a set of all of the names from removals list.
    removal_names = {cache[path].get("name") for path in removals if path in
                     cache}
    # The difference tells us which products we are completely removing.
    names_to_remove = removal_names - remaining_names
    return names_to_remove


def print_removals(removals, removal_type):
    """Pretty print the files to remove."""
    print "Items to be {}".format(removal_type)
    for item in sorted(removals):
        print "\t{}".format(item)

    print


def print_manifest_removals(names):
    """Pretty print the names to remove from manifests."""
    print "Items to be removed from manifests:"
    for item in sorted(names):
        print "\t{}".format(item)

    print


def warn_about_multiple_refs(removals, cache):
    """Alert user about possible pkg removal dependencies."""
    # Check for pkginfo files that are NOT to be removed which reference
    # any pkgs to be removed and warn the user!
    for path, plist in cache.items():
        if (not path in removals and
                plist.get("installer_item_location") in removals):
            print ("WARNING: Package '{}' is targeted for removal, but has "
                   "references in pkginfo '{}' which is not targeted for "
                   "removal.".format(
                       plist.get("intaller_item_location"), path))


def move_to_archive(removals, archive_path):
    """Move a list of files to an archive folder."""
    pkgs_folder = os.path.join(archive_path, "pkgs")
    pkgsinfo_folder = os.path.join(archive_path, "pkgsinfo")
    for folder in (pkgs_folder, pkgsinfo_folder):
        make_folders(folder)

    repo_prefix = tools.get_repo_path()
    for item in removals:
        if item:
            archive_item = item.replace(repo_prefix, archive_path, 1)
            make_folders(os.path.dirname(archive_item))
            # TODO: Need to add Git awareness.
            shutil.move(item, archive_item)


def make_folders(folder):
    """Make all folders in path that are missing."""
    if not os.path.exists(folder):
        try:
            os.makedirs(folder)
        except OSError:
            print ("Failed to create archive directory {}! "
                   "Quitting.".format(folder))
            sys.exit(1)


def remove(removals):
    """Delete a list of files."""
    for item in removals:
        if item:
            try:
                os.remove(item)
            except OSError as error:
                print ("Unable to remove {} with error: {}".format(
                    item, error.message))


def remove_names_from_manifests(names):
    """Remove names from all manifests."""
    if not names:
        return
    # Build a new cache post-removal. We haven't run makecatalogs, so
    # we can't use the catalogs for this task.
    repo_path = tools.get_repo_path()
    manifests_path = os.path.join(repo_path, "manifests")

    cache = tools.build_pkginfo_cache(repo_path)
    remaining_names = {pkginfo.get("name") for pkginfo in cache.values()}
    # Use set arithmetic to remove names that are still active in the
    # repo from our removals set.
    names_to_remove = names - remaining_names

    keys = ("managed_installs", "optional_installs", "managed_updates",
            "managed_uninstalls")

    for manifest_path in glob.glob(os.path.join(manifests_path, "*")):
        changed = False
        try:
            manifest = FoundationPlist.readPlist(manifest_path)
        except FoundationPlist.FoundationPlistException:
            print "Error reading manifest {}".format(manifest_path)
            continue
        print "Looking for name removals in {}".format(manifest_path)

        for key in keys:
            product_array = manifest.get(key)
            if product_array:
                changes = handle_name_removal(product_array, names_to_remove,
                                              key)
                if changes:
                    changed = True

        # TODO: This can be refactored out as it's a duplicate, just
        # one layer deeper in the manifest.
        if "conditional_items" in manifest:
            conditionals = manifest["conditional_items"]
            for conditional in conditionals:
                for key in keys:
                    product_array = conditional.get(key)
                    if product_array:
                        changes = handle_name_removal(
                            product_array, names_to_remove,
                            "conditional " + key)
                        if changes:
                            changed = True

        if changed:
            FoundationPlist.writePlist(manifest, manifest_path)


def handle_name_removal(product_array, names_to_remove, key):
    """Remove names from a manifest."""
    removals = []
    changes = False
    for item in product_array:
        if item in names_to_remove:
            print "\tRemoving {} from {}".format(item, key)
            removals.append(item)
        elif (item.startswith(tuple(names_to_remove)) and not
              item.endswith(tuple(names_to_remove))):
            print ("\tDeprecator found item {} that may match a "
                   "name to remove, but the length is wrong. "
                   "Please remove manually if required!").format(item)
    for item in removals:
        product_array.remove(item)
        changes = True

    return changes


if __name__ == "__main__":
    main()