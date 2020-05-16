# anki-search-inside-add-card
# Copyright (C) 2019 - 2020 Tom Z.

# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.

# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Affero General Public License for more details.

# You should have received a copy of the GNU Affero General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.


import platform
import os
import json
import re
import time
from datetime import datetime as dt
import sys
import typing
import aqt
import uuid
from aqt import mw
from aqt.utils import showInfo, tooltip

import utility.tags
import utility.text
import utility.misc
import utility.date

from ..tag_find import get_most_active_tags
from ..state import get_index, check_index, set_deck_map
from ..notes import *
from ..notes import _get_priority_list
from .html import *
from .note_templates import *
from ..internals import js, requires_index_loaded, perf_time
from ..config import get_config_value_or_default
from ..web_import import import_webpage
from ..stats import getRetentions


class ReadingModal:

    def __init__(self):
        self.note_id = None
        self.note = None
        self._editor = None

        self.highlight_color = "#e65100"
        self.highlight_type = 1

        self.sidebar = ReadingModalSidebar()

    def set_editor(self, editor):
        self._editor = editor
        self.sidebar.set_editor(editor)

    def reset(self):
        self.note_id = None
        self.note = None

    @requires_index_loaded
    def display(self, note_id):

        index = get_index()
        note = get_note(note_id)

        self.note_id = note_id
        self.note = note

        html = get_reading_modal_html(note)
        index.ui.show_in_large_modal(html)

        # wrap fields in tabs
        index.ui.js("""
            $(document.body).addClass('siac-reading-modal-displayed');
            if (!document.getElementById('siac-reading-modal-tabs-left')) {
                $('#siac-left-tab-browse,#siac-left-tab-pdfs,#siac-reading-modal-tabs-left').remove();
                document.getElementById('leftSide').innerHTML += `
                    <div id='siac-reading-modal-tabs-left'>
                        <div class='siac-btn siac-btn-dark active' onclick='modalTabsLeftClicked("flds", this);'>Fields</div>
                        <div class='siac-btn siac-btn-dark' onclick='modalTabsLeftClicked("browse", this);'>Browse</div>
                        <div class='siac-btn siac-btn-dark' onclick='modalTabsLeftClicked("pdfs", this);'>PDFs</div>
                    </div>
                `;
            }
        """)

        # if source is a pdf file path, try to display it
        if note.is_pdf():
            if utility.misc.file_exists(note.source):
                self._display_pdf(note.source.strip(), note_id)
            else:
                message = "Could not load the given PDF.<br>Are you sure the path is correct?"
                self.notification(message)

        # auto fill tag entry if pdf has tags and config option is set
        if note.tags is not None and len(note.tags.strip()) > 0 and get_config_value_or_default("pdf.onOpen.autoFillTagsWithPDFsTags", True):
            self._editor.tags.setText(" ".join(mw.col.tags.canonify(mw.col.tags.split(note.tags))))

        # auto fill user defined fields
        fields_to_prefill = get_config_value_or_default("pdf.onOpen.autoFillFieldsWithPDFName", [])
        if len(fields_to_prefill) > 0:
            for f in fields_to_prefill:
                title = note.get_title().replace("`", "&#96;")
                if f in self._editor.note:
                    i = self._editor.note._fieldOrd(f)
                    self._editor.web.eval(f"$('.field').eq({i}).text(`{title}`);")

    def display_head_of_queue(self):
        recalculate_priority_queue()
        nid = get_head_of_queue()
        if nid is not None and nid >= 0:
            self.display(nid)
        else:
            tooltip("Queue is empty.")

    @js
    def show_width_picker(self):
        html = """
            <div class='w-100 siac-rm-main-color-hover' onclick='pycmd("siac-left-side-width 10")'><b>10 - 90</b></div>
            <div class='w-100 siac-rm-main-color-hover' onclick='pycmd("siac-left-side-width 15")'><b>15 - 85</b></div>
            <div class='w-100 siac-rm-main-color-hover' onclick='pycmd("siac-left-side-width 25")'><b>25 - 75</b></div>
            <div class='w-100 siac-rm-main-color-hover' onclick='pycmd("siac-left-side-width 33")'><b>33 - 67</b></div>
            <div class='w-100 siac-rm-main-color-hover' onclick='pycmd("siac-left-side-width 40")'><b>40 - 60</b></div>
            <div class='w-100 siac-rm-main-color-hover' onclick='pycmd("siac-left-side-width 50")'><b>50 - 50</b></div>
            <div class='w-100 siac-rm-main-color-hover' onclick='pycmd("siac-left-side-width 60")'><b>60 - 40</b></div>
            <div class='w-100 siac-rm-main-color-hover' onclick='pycmd("siac-left-side-width 67")'><b>67 - 33</b></div>
        """

        modal = """
            <div class="siac-modal-small dark" contenteditable="false" style="text-align:center; color: lightgrey;">
                <b>Width (%%)</b><br>
                <b>Fields - Add-on</b>
                    <br><br>
                <div style="max-height: 200px; overflow-y: auto; overflow-x: hidden;">%s</div>
                    <br><br>
                <div class="siac-btn siac-btn-dark" onclick="$(this.parentNode).remove();">Close</div>
            </div>
        """ % html
        return "$('#siac-reading-modal-center').append(`%s`)" % modal

    @js
    def display_read_range_input(self, note_id, num_pages):
        on_confirm= """ if (document.getElementById('siac-range-input-min').value && document.getElementById('siac-range-input-max').value) {
        pycmd('siac-user-note-mark-range %s ' + document.getElementById('siac-range-input-min').value
                + ' ' + document.getElementById('siac-range-input-max').value
                + ' ' + pdfDisplayed.numPages
                + ' ' + pdfDisplayedCurrentPage);
        }
        """ % note_id
        modal = f""" <div class="siac-modal-small dark" contenteditable="false" style="text-align:center; color: lightgrey;">
                            Input a range of pages to mark as read (end incl.)<br><br>
                            <input id='siac-range-input-min' style='width: 60px; background: #222; color: lightgrey; border-radius: 4px;' type='number' min='1' max='{num_pages}'/> &nbsp;-&nbsp; <input id='siac-range-input-max' style='width: 60px;background: #222; color: lightgrey; border-radius: 4px;' type='number' min='1' max='{num_pages}'/>
                            <br/> <br/>
                            <div class="siac-btn siac-btn-dark" onclick="{on_confirm} $(this.parentNode).remove();">&nbsp; Ok &nbsp;</div>
                            &nbsp;
                            <div class="siac-btn siac-btn-dark" onclick="$(this.parentNode).remove();">Cancel</div>
                        </div> """
        return "$('#siac-pdf-tooltip').hide();$('.siac-modal-small').remove(); $('#siac-reading-modal-center').append('%s');" % modal.replace("\n", "").replace("'", "\\'")


    @js
    def reload_bottom_bar(self, note_id=None):
        """
            Called after queue picker dialog has been closed without opening a new note.
        """
        if note_id is not None:

            note = get_note(note_id)
            html = get_reading_modal_bottom_bar(note)
            html = html.replace("`", "\\`")
            return "$('#siac-reading-modal-bottom-bar').replaceWith(`%s`); updatePdfDisplayedMarks();" % html

        else:
            return """if (document.getElementById('siac-reading-modal').style.display !== 'none' && document.getElementById('siac-reading-modal-top-bar')) {
                        pycmd('siac-reload-reading-modal-bottom '+ $('#siac-reading-modal-top-bar').data('nid'));
                    }"""


    def _display_pdf(self, full_path, note_id):
        base64pdf = utility.misc.pdf_to_base64(full_path)
        blen = len(base64pdf)

        #pages read are stored in js array [int]
        pages_read = get_read_pages(note_id)
        pages_read_js = "" if len(pages_read) == 0 else ",".join([str(p) for p in pages_read])

        #marks are stored in two js maps, one with pages as keys, one with mark types (ints) as keys
        marks = get_pdf_marks(note_id)
        js_maps = utility.misc.marks_to_js_map(marks)
        marks_js = "pdfDisplayedMarks = %s; pdfDisplayedMarksTable = %s;" % (js_maps[0], js_maps[1])

        # pages read are ordered by date, so take last
        last_page_read = pages_read[-1] if len(pages_read) > 0 else 1

        addon_id = utility.misc.get_addon_id()
        port = mw.mediaServer.getPort()

        init_code = """
            pdfLoading = true;
            var bstr = atob(b64);
            var n = bstr.length;
            var arr = new Uint8Array(n);
            while(n--){
                arr[n] = bstr.charCodeAt(n);
            }
            var file = new File([arr], "placeholder.pdf", {type : "application/pdf" });
            var fileReader = new FileReader();
            pagesRead = [%s];
            %s
            var loadFn = function(retry) {
                if (retry > 4) {
                    $('#siac-pdf-loader-wrapper').remove();
                    document.getElementById('siac-pdf-top').style.overflowY = 'auto';
                    $('#siac-timer-popup').html(`<br><center>PDF.js could not be loaded from CDN.</center><br>`).show();
                    pdfDisplayed = null;
                    ungreyoutBottom();
                    fileReader = null;
                    pdfLoading = false;
                    noteLoading = false;
                    return;
                }
                if (typeof(pdfjsLib) === 'undefined') {
                    window.setTimeout(() => { loadFn(retry + 1);}, 800);
                    document.getElementById('siac-loader-text').innerHTML = `PDF.js was not loaded. Retrying (${retry+1} / 5)`;
                    return;
                }
                if (!pdfjsLib.GlobalWorkerOptions.workerSrc) {
                    pdfjsLib.GlobalWorkerOptions.workerSrc = 'http://127.0.0.1:%s/_addons/%s/web/pdfjs/pdf.worker.min.js';
                }
                var canvas = document.getElementById("siac-pdf-canvas");
                var typedarray = new Uint8Array(fileReader.result);
                var loadingTask = pdfjsLib.getDocument(typedarray, {nativeImageDecoderSupport: 'display'});
                loadingTask.promise.catch(function(error) {
                        console.log(error);
                        $('#siac-pdf-loader-wrapper').remove();
                        document.getElementById('siac-pdf-top').style.overflowY = 'auto';

                        $('#siac-timer-popup').html(`<br><center>Could not load PDF - seems to be invalid.</center><br>`).show();
                        pdfDisplayed = null;
                        ungreyoutBottom();
                        fileReader = null;
                        pdfLoading = false;
                        noteLoading = false;
                });
                loadingTask.promise.then(function(pdf) {
                        pdfDisplayed = pdf;
                        pdfDisplayedCurrentPage = %s;
                        $('#siac-pdf-loader-wrapper').remove();
                        document.getElementById('siac-pdf-top').style.overflowY = 'auto';

                        if (pagesRead.length === pdf.numPages) {
                            pdfDisplayedCurrentPage = 1;
                            queueRenderPage(1, true, true, true);
                        } else {
                            queueRenderPage(pdfDisplayedCurrentPage, true, true, true);
                        }
                        updatePdfProgressBar();
                        if (pagesRead.length === 0) { pycmd('siac-insert-pages-total %s ' + pdf.numPages); }
                        fileReader = null;
                });
            };
            fileReader.onload = (e) => { loadFn(0); };

            fileReader.readAsArrayBuffer(file);
            b64 = ""; arr = null; bstr = null; file = null;
        """ % (pages_read_js, marks_js, port, addon_id, last_page_read, note_id)
        #send large files in multiple packets
        page = self._editor.web.page()
        chunk_size = 10000000
        if blen > chunk_size:
            page.runJavaScript(f"var b64 = `{base64pdf[0: chunk_size]}`;")
            sent = chunk_size
            while sent < blen:
                page.runJavaScript(f"b64 += `{base64pdf[sent: min(blen,sent + chunk_size)]}`;")
                sent += min(blen - sent, chunk_size)
            page.runJavaScript(init_code)
        else:
            page.runJavaScript("""
                var b64 = `%s`;
                    %s
            """ % (base64pdf, init_code))

    def show_fields_tab(self):
        self.sidebar.show_fields_tab()

    def show_browse_tab(self):
        self.sidebar.show_browse_tab()

    def show_pdfs_tab(self):
        self.sidebar.show_pdfs_tab()

    @js
    def display_schedule_dialog(self):
        """
            Called when the currently opened note has a schedule and after it is finished reading.
        """

        if self.note.is_due_sometime():
            delta = self.note.due_days_delta()
        else:
            delta = 0

        if delta == 0:
            header = "This note was scheduled for <b>today</b>."
        elif delta == 1:
            header = "This note was scheduled for <b>yesterday</b>, but not marked as done."
        elif delta  == -1:
            header = "This note is due <b>tomorrow</b>."
        elif delta < -1:
            header = f"This note is due in <b>{abs(delta)}</b> days."
        else:
            header = f"This note was due <b>{delta}</b> days ago, but not marked as done."

        header +="<br>How do you want to proceed?"
        options = ""

      
        if delta < 0:
            options += """
                    <label class='blue-hover' for='siac-rb-1'>
                        <input id='siac-rb-1' type='radio' name='sched' data-pycmd="1" checked>
                        <span>Keep that Schedule</span>
                    </label><br>
            """
        else:
            if self.note.schedule_type() == "td":
                days_delta = int(self.note.reminder.split("|")[2][3:])
                s = "s" if days_delta > 1 else ""
                options += f"""
                    <label class='blue-hover' for='siac-rb-1'>
                        <input id='siac-rb-1' type='radio' name='sched' data-pycmd="1" checked>
                        <span>Show again in <b>{days_delta}</b> day{s}</span>
                    </label><br>
                """
            elif self.note.schedule_type() == "wd":
                weekdays_due = [int(d) for d in self.note.reminder.split("|")[2][3:]]
                next_date_due = utility.date.next_instance_of_weekdays(weekdays_due)
                weekday_name = utility.date.weekday_name(next_date_due.weekday() + 1)
                options += f"""
                    <label class='blue-hover' for='siac-rb-1'>
                        <input id='siac-rb-1' type='radio' name='sched' data-pycmd="1" checked>
                        <span>Show again next <b>{weekday_name}</b></span>
                    </label><br>
                """
            elif self.note.schedule_type() == "id":
                days_delta = int(self.note.reminder.split("|")[2][3:])
                s = "s" if days_delta > 1 else ""
                options += f"""
                    <label class='blue-hover' for='siac-rb-1'>
                        <input id='siac-rb-1' type='radio' name='sched' data-pycmd="1" checked>
                        <span>Show again in <b>{days_delta}</b> day{s}</span>
                    </label><br>
                """


        options += """
                <label class='blue-hover' for='siac-rb-2'>
                    <input id='siac-rb-2' type='radio' name='sched' data-pycmd="2">
                    <span>Rem. Schedule, but keep in Queue</span>
                </label><br>
                <label class='blue-hover' for='siac-rb-3'>
                    <input id='siac-rb-3' type='radio' name='sched' data-pycmd="3">
                    <span>Remove from Queue</span>
                </label><br>
            """

        modal = f"""
            <div id='siac-schedule-dialog' class="siac-modal-small dark" style="text-align:center;">
                {header}

                <div class='siac-pdf-main-color-border-bottom siac-pdf-main-color-border-top' style='text-align: left; user-select: none; cursor: pointer; margin: 10px 0 10px 0; padding: 15px;'>
                  {options}

                </div>
                <div style='text-align: left;'>
                    <a class='siac-clickable-anchor' onclick='pycmd("siac-eval index.ui.reading_modal.show_schedule_change_modal()")'>Change Scheduling</a>
                    <div class='siac-btn siac-btn-dark' style='float: right;' onclick='scheduleDialogQuickAction()'>Ok</div>
                </div>

            </div>
        """
        return """modalShown=true;
            $('#siac-rm-greyout').show();
            if (document.getElementById('siac-schedule-dialog')) {
                $('#siac-schedule-dialog').replaceWith(`%s`);
            } else {
                $('#siac-reading-modal-center').append(`%s`);
            }
            """ % (modal, modal)


    @js
    def show_remove_dialog(self):
        """
            Shows a dialog to either remove the current note from the queue or to delete it altogether.
        """
        title = utility.text.trim_if_longer_than(self.note.get_title(), 40).replace("`", "")
        rem_cl = "checked" if self.note.position is not None and self.note.position >= 0 else "disabled"
        del_cl = "checked" if self.note.position is None or self.note.position < 0 else ""
        modal = f"""
            <div id='siac-schedule-dialog' class="siac-modal-small dark" style="text-align:center;">
                Remove / delete this note?<br><br>
                {title}

                <div class='siac-pdf-main-color-border-bottom siac-pdf-main-color-border-top' style='text-align: left; user-select: none; cursor: pointer; margin: 10px 0 10px 0; padding: 15px;'>
                    <label class='blue-hover' for='siac-rb-1'>
                        <input id='siac-rb-1' type='radio' {rem_cl} name='del' data-pycmd="1">
                        <span>Remove from Queue</span>
                    </label><br>
                    <label class='blue-hover' for='siac-rb-2'>
                        <input id='siac-rb-2' type='radio' {del_cl} name='del' data-pycmd="2">
                        <span>Delete Note</span>
                    </label><br>

                </div>
                <div style='text-align: right;'>
                    <div class='siac-btn siac-btn-dark' style='margin-right: 10px;' onclick='$(this.parentNode.parentNode).remove(); modalShown = false; ungreyoutBottom(); $("#siac-rm-greyout").hide();'>Cancel</div>
                    <div class='siac-btn siac-btn-dark' onclick='removeDialogOk()'>Ok</div>
                </div>

            </div>
        """
        return """modalShown=true;
            $('#siac-timer-popup').hide();
            $('#siac-rm-greyout').show();
            $('#siac-reading-modal-center').append(`%s`);
            """ % (modal)

    @js
    def show_schedule_change_modal(self, unscheduled=False):

        title = "Set a new Schedule" if not unscheduled else "This note had no schedule before."
        if not unscheduled:
            back_btn = """<a class='siac-clickable-anchor' onclick='pycmd("siac-eval index.ui.reading_modal.display_schedule_dialog()")'>Back</a>"""
        else:
            back_btn = """<a class='siac-clickable-anchor' onclick='pycmd("siac-eval index.ui.reading_modal.display_head_of_queue()")'>Proceed without scheduling</a>"""

        body = f"""
                {title}
                <div class='siac-pdf-main-color-border-bottom siac-pdf-main-color-border-top' style='text-align: left; user-select: none; cursor: pointer; margin: 10px 0 10px 0; padding: 15px;'>

                    <label class='blue-hover' for='siac-rb-4'>
                        <input id='siac-rb-4' type='radio' data-pycmd='4' checked name='sched'>
                        <span>Show again in [n] days:</span>
                    </label><br>
                    <div class='w-100' style='margin: 10px 0 10px 0;'>
                        <input id='siac-sched-td-inp' type='number' min='1' style='width: 70px; color: lightgrey; border: 2px outset #b2b2a0; background: transparent;'/>
                        <div class='siac-btn siac-btn-dark' style='margin-left: 15px;' onclick='document.getElementById("siac-sched-td-inp").value = 1;'>Tomorrow</div>
                        <div class='siac-btn siac-btn-dark' style='margin-left: 5px;' onclick='document.getElementById("siac-sched-td-inp").value = 7;'>In 7 Days</div>
                    </div>
                    <label class='blue-hover' for='siac-rb-5'>
                        <input id='siac-rb-5' type='radio'  data-pycmd='5' name='sched'>
                        <span>Show on Weekday(s):</span>
                    </label><br>
                    <div class='w-100' style='margin: 10px 0 10px 0;' id='siac-sched-wd'>
                        <label><input type='checkbox' style='vertical-align: middle;'/>M</label>
                        <label style='margin: 0 0 0 4px;'><input style='vertical-align: middle;' type='checkbox'/>T</label>
                        <label style='margin: 0 0 0 4px;'><input style='vertical-align: middle;' type='checkbox'/>W</label>
                        <label style='margin: 0 0 0 4px;'><input style='vertical-align: middle;' type='checkbox'/>T</label>
                        <label style='margin: 0 0 0 4px;'><input style='vertical-align: middle;' type='checkbox'/>F</label>
                        <label style='margin: 0 0 0 4px;'><input style='vertical-align: middle;' type='checkbox'/>S</label>
                        <label style='margin: 0 0 0 4px;'><input style='vertical-align: middle;' type='checkbox'/>S</label>
                    </div>

                    <label class='blue-hover' for='siac-rb-6'>
                        <input id='siac-rb-6' type='radio'  data-pycmd='6' name='sched'>
                        <span>Show every [n]th Day</span>
                    </label><br>
                    <div class='w-100' style='margin: 10px 0 10px 0;'>
                        <input id='siac-sched-id-inp' type='number' min='1' style='width: 70px; color: lightgrey; border: 2px outset #b2b2a0; background: transparent;'/>
                    </div>

                </div>
                <div style='text-align: left;'>
                    {back_btn}
                    <div class='siac-btn siac-btn-dark' style='float: right;' onclick='updateSchedule()'>Set Schedule</div>
                </div>
        """
        return f"""
            if (document.getElementById('siac-schedule-dialog')) {{
                document.getElementById("siac-schedule-dialog").innerHTML = `{body}`;
            }} else {{
                $('#siac-reading-modal-center').append(`<div id='siac-schedule-dialog' class="siac-modal-small dark" style="text-align:center;">{body}</div>`);
            }}
        """

    def schedule_note(self, option: int):
        delta = self.note.due_days_delta()
        now = utility.date.date_now_stamp()
        new_prio = get_priority(self.note_id)
        if option == 1:
            if delta < 0:
                # keep schedule & requeue
                new_reminder = self.note.reminder
            else:
                if self.note.schedule_type() == "td":
                    # show again in n days
                    days_delta = int(self.note.reminder.split("|")[2][3:])
                    next_date_due = dt.now() + timedelta(days=days_delta)
                    new_reminder = f"{now}|{utility.date.dt_to_stamp(next_date_due)}|td:{days_delta}"

                elif self.note.schedule_type() == "wd":
                    # show again on next weekday instance
                    wd_part = self.note.reminder.split("|")[2]
                    weekdays_due = [int(d) for d in wd_part[3:]]
                    next_date_due = utility.date.next_instance_of_weekdays(weekdays_due)
                    new_reminder = f"{now}|{utility.date.dt_to_stamp(next_date_due)}|{wd_part}"
                elif self.note.schedule_type() == "id":
                    # show again according to interval
                    days_delta = int(self.note.reminder.split("|")[2][3:])
                    next_date_due = dt.now() + timedelta(days=days_delta)
                    new_reminder = f"{now}|{utility.date.dt_to_stamp(next_date_due)}|id:{days_delta}"
        elif option == 2:
            #remove schedule & requeue
            new_reminder = ""
        elif option == 3:
            # remove entirely from queue
            new_reminder = ""
            new_prio = 0

        update_reminder(self.note_id, new_reminder)
        update_priority_list(self.note_id, new_prio)
        nid = get_head_of_queue()
        if nid is not None and nid >= 0:
            self.display(nid)
        else:
            self._editor.web.eval("""
                onReadingModalClose();
            """)

    @js
    def show_theme_dialog(self):
        modal = f"""
            <div id='siac-schedule-dialog' class="siac-modal-small dark" style="text-align:center;">
                Change the main color of the reader.<br><br>
                <div style='user-select: none;'>
                    <a class='siac-clickable-anchor' onclick='setPdfTheme("pdf_reader.css")'>Orange</a><br>
                    <a class='siac-clickable-anchor' onclick='setPdfTheme("pdf_reader_lightblue.css")'>Lightblue</a><br>
                    <a class='siac-clickable-anchor' onclick='setPdfTheme("pdf_reader_khaki.css")'>Khaki</a><br>
                    <a class='siac-clickable-anchor' onclick='setPdfTheme("pdf_reader_darkseagreen.css")'>Darkseagreen</a><br>
                    <a class='siac-clickable-anchor' onclick='setPdfTheme("pdf_reader_tan.css")'>Tan</a><br>
                    <a class='siac-clickable-anchor' onclick='setPdfTheme("pdf_reader_lightgreen.css")'>Lightgreen</a><br>
                    <a class='siac-clickable-anchor' onclick='setPdfTheme("pdf_reader_lightsalmon.css")'>Lightsalmon</a><br>
                    <a class='siac-clickable-anchor' onclick='setPdfTheme("pdf_reader_yellow.css")'>Yellow</a><br>
                    <a class='siac-clickable-anchor' onclick='setPdfTheme("pdf_reader_crimson.css")'>Crimson</a><br>
                    <a class='siac-clickable-anchor' onclick='setPdfTheme("pdf_reader_steelblue.css")'>Steelblue</a><br>
                </div>
                <br>
                <div style='text-align: right;'>
                    <div class='siac-btn siac-btn-dark' style='margin-right: 10px;' onclick='$(this.parentNode.parentNode).remove(); modalShown = false; ungreyoutBottom(); $("#siac-rm-greyout").hide();'>Ok</div>
                </div>

            </div>
        """
        return """modalShown=true;
            $('#siac-timer-popup').hide();
            $('#siac-rm-greyout').show();
            $('#siac-reading-modal-center').append(`%s`);
            """ % (modal)



    @js
    def show_img_field_picker_modal(self, img_src):
        """
            Called after an image has been selected from a PDF, should display all fields that are currently in the editor,
            let the user pick one, and on picking, insert the img into the field.
        """
        # if Image Occlusion add-on is there and enabled, add a button to directly open the IO dialog
        io = ""
        if hasattr(self._editor, 'onImgOccButton') and mw.addonManager.isEnabled("1374772155"):
            io = f"<div class='siac-btn siac-btn-dark' style='margin-right: 9px;' onclick='pycmd(`siac-cutout-io {img_src}`); $(this.parentNode).remove();'>Image Occlusion</div>"
        modal = """ <div class="siac-modal-small dark" style="text-align:center;"><b>Append to:</b><br><br><div style="max-height: 200px; overflow-y: auto; overflow-x: hidden;">%s</div><br><br>%s<div class="siac-btn siac-btn-dark" onclick="$(this.parentNode).remove(); pycmd('siac-remove-snap-image %s')">Cancel</div></div> """
        flds = ""
        for i, f in enumerate(self._editor.note.model()['flds']):
            # trigger note update
            fld_update_js = "pycmd(`blur:%s:${currentNoteId}:${$(`.field:eq(%s)`).html()}`);" % (i,i)
            flds += """<span class="siac-field-picker-opt" onclick="$(`.field`).get(%s).innerHTML += `<img src='%s'/>`; $(this.parentNode.parentNode).remove(); %s">%s</span><br>""" % (i, img_src, fld_update_js, f["name"])
        modal = modal % (flds, io, img_src)
        return "$('#siac-reading-modal-center').append('%s');" % modal.replace("'", "\\'")

    @js
    def show_cloze_field_picker_modal(self, cloze_text):
        """
        Shows a modal that lists all fields of the current note.
        When a field is selected, the cloze text is appended to that field.
        """
        cloze_text = cloze_text.replace("`", "").replace("\n", "")
        modal = """ <div class="siac-modal-small dark" style="text-align:center;">
                        <b>Append to:</b><br><br>
                        <div style="max-height: 200px; overflow-y: auto; overflow-x: hidden;">%s</div><br><br>
                        <div class="siac-btn siac-btn-dark" onclick="$(this.parentNode).remove();">Cancel</div>
                    </div> """
        flds = ""
        for i, f in enumerate(self._editor.note.model()['flds']):
            flds += """<span class="siac-field-picker-opt" onclick="appendToField({0}, `{1}`);  $(this.parentNode.parentNode).remove();">{2}</span><br>""".format(i, cloze_text, f["name"])
        modal = modal % (flds)
        return "$('#siac-pdf-tooltip').hide(); $('#siac-reading-modal-center').append('%s');" % modal.replace("\n", "").replace("'", "\\'")

    @js
    def show_iframe_overlay(self, url=None):
        js = """
            if (pdfDisplayed) {
                document.getElementById('siac-pdf-top').style.display = "none";
            } else {
                document.getElementById('siac-text-top-wr').style.display = "none";
            }
            document.getElementById('siac-iframe').style.display = "block";
            document.getElementById('siac-close-iframe-btn').style.display = "block";
            iframeIsDisplayed = true;
        """
        if url is not None:
            js += """
                document.getElementById('siac-iframe').src = `%s`;
            """ % url
        return js

    @js
    def hide_iframe_overlay(self):
        js = """
            document.getElementById('siac-iframe').src = "";
            document.getElementById('siac-iframe').style.display = "none";
            document.getElementById('siac-close-iframe-btn').style.display = "none";
            if (pdfDisplayed) {
                document.getElementById('siac-pdf-top').style.display = "block";
            } else {
                document.getElementById('siac-text-top-wr').style.display = "block";
            }
            iframeIsDisplayed = false;
        """
        return js

    @js
    def show_web_search_tooltip(self, inp):
        inp = utility.text.remove_special_chars(inp)
        inp = inp.strip()
        if len(inp) == 0:
            return
        search_sources = ""
        config = mw.addonManager.getConfig(__name__)
        urls = config["searchUrls"]
        if urls is not None and len(urls) > 0:
            for url in urls:
                if "[QUERY]" in url:
                    name = os.path.dirname(url)
                    search_sources += """<div class="siac-url-ch" onclick='pycmd("siac-url-srch $$$" + document.getElementById("siac-tt-ws-inp").value + "$$$%s"); $(this.parentNode.parentNode).remove();'>%s</div>""" % (url, name)

        modal = """ <div class="siac-modal-small dark" style="text-align:center;">
                        <input style="width: 100%%; border-radius: 3px; padding-left: 4px; box-sizing: border-box; background: #2f2f31; color: white; border-color: white;" id="siac-tt-ws-inp" value="%s"></input>
                        <br/>
                        <div style="max-height: 200px; overflow-y: auto; overflow-x: hidden; cursor: pointer; margin-top: 15px;">%s</div><br><br>
                        <div class="siac-btn siac-btn-dark" onclick="$(this.parentNode).remove();">Cancel</div>
                    </div> """% (inp, search_sources)

        js = """
        $('#siac-iframe-btn').removeClass('expanded');
        $('#siac-pdf-tooltip').hide();
        $('#siac-reading-modal-center').append('%s');
        """ % modal.replace("\n", "").replace("'", "\\'")
        return js

    @js
    def update_reading_bottom_bar(self, nid):
        queue = _get_priority_list()
        pos_lbl = ""
        if queue is not None and len(queue) > 0:
            try:
                pos = next(i for i,v in enumerate(queue) if v.id == nid)
            except:
                pos = -1
            pos_lbl = "Priority: " + get_priority_as_str(nid)
            # pos_lbl_btn = f"Queue [{pos + 1}]" if pos >= 0 else "Unqueued"
            pos_lbl_btn = f"Priority" if pos >= 0 else "Unqueued"
        else:
            pos_lbl = "Unqueued"
            pos_lbl_btn = "<b>Unqueued</b>"

        qd = get_queue_head_display(nid, queue)
        return """
            document.getElementById('siac-queue-lbl').innerHTML = '%s';
            $('#siac-queue-lbl').fadeIn('slow');
            $('.siac-queue-sched-btn:first').html('%s');
            $('#siac-queue-readings-list').replaceWith(`%s`);
            """ % (pos_lbl, pos_lbl_btn, qd)

    @js
    def show_pdf_bottom_tab(self, note_id, tab):
        tab_js = "$('.siac-clickable-anchor.tab').removeClass('active');"
        if tab == "marks":
            return f"""{tab_js}
            $('.siac-clickable-anchor.tab').eq(0).addClass('active');
            document.getElementById('siac-pdf-bottom-tab').innerHTML =`<div id='siac-marks-display' onclick='markClicked(event);'></div>`;
            updatePdfDisplayedMarks()"""
        if tab == "info":
            html = get_note_info_html(note_id)
            html = html.replace("`", "&#96;")
            return f"""{tab_js}
            $('.siac-clickable-anchor.tab').eq(2).addClass('active');
            document.getElementById('siac-pdf-bottom-tab').innerHTML =`{html}`;"""
        if tab == "related":
            html = get_related_notes_html(note_id)
            html = html.replace("`", "&#96;")
            return f"""{tab_js}
            $('.siac-clickable-anchor.tab').eq(1).addClass('active');
            document.getElementById('siac-pdf-bottom-tab').innerHTML =`{html}`;"""


    @js
    def mark_range(self, start, end, pages_total, current_page):
        if start <= 0:
            start = 1
        if end > pages_total:
            end = pages_total
        if end <= start or start >= pages_total:
            return
        mark_range_as_read(self.note_id, start, end, pages_total)
        pages_read = get_read_pages(self.note_id)
        js = "" if len(pages_read) == 0 else ",".join([str(p) for p in pages_read])
        js = f"pagesRead = [{js}];"
        if current_page >= start and current_page <= end:
            js += "pdfShowPageReadMark();"
        return f"{js}updatePdfProgressBar();"

    @js
    def display_cloze_modal(self, editor, selection, extracted):
        s_html = "<table style='margin-top: 5px; font-size: 15px;'>"
        sentences = [s for s in extracted if len(s) < 300 and len(s.strip()) > 0]
        if len(sentences) == 0:
            for s in extracted:
                if len(s) >= 300:
                    f = utility.text.try_find_sentence(s, selection)
                    if f is not None and len(f) < 300:
                        sentences.append(f)

        if len(sentences) > 0 and sentences != [""]:
            selection = re.sub("  +", " ", selection).strip()
            for sentence in sentences:
                sentence = re.sub("  +", " ", sentence).strip()
                sentence = sentence.replace(selection, " <span style='color: lightblue;'>{{c1::%s}}</span> " % selection)

                # needs cleaning
                sentence = sentence.replace("  ", " ").replace("</span> ,", "</span>,")
                sentence = re.sub(" ([\"“”\\[(]) <span", " \\1<span", sentence)
                sentence = re.sub("</span> ([\"”\\]):])", "</span>\\1", sentence)
                sentence = re.sub("</span> -([^ \\d])", "</span>-\\1", sentence)
                sentence = re.sub("(\\S)- <span ", "\\1-<span ", sentence)
                sentence = re.sub(r"([^\\d ])- ([^\d])", r"\1\2", sentence)
                sentence = re.sub(" [\"“”], [\"“”] ?", "\", \"", sentence)
                sentence = re.sub(" [\"“”], ", "\", ", sentence)
                sentence = re.sub(": [\"“”] ", ": \"", sentence)
                sentence = sentence.replace("[ ", "[")
                sentence = sentence.replace(" ]", "]")
                sentence = re.sub(" ([,;:.]) ", r"\1 ", sentence)
                sentence = re.sub(r"\( (.) \)", r"(\1)", sentence)
                sentence = re.sub(" ([?!.])$", r"\1", sentence)
                sentence = re.sub("^[:.?!,;)] ", "", sentence)
                sentence = re.sub("^\\d+ ?[:\\-.,;] ([A-ZÖÄÜ])", r"\1", sentence)

                sentence = re.sub(" ([\"“”])([?!.])$", r"\1\2", sentence)

                s_html += "<tr class='siac-cl-row'><td><div contenteditable class='siac-pdf-main-color'>%s</div></td><td><input type='checkbox' checked/></td></tr>" % (sentence.replace("`", "&#96;"))
            s_html += "</table>"
            btn_html = """document.getElementById('siac-pdf-tooltip-bottom').innerHTML = `
                                <div style='margin-top: 8px;'>
                                <div class='siac-btn siac-btn-dark' onclick='pycmd("siac-fld-cloze " +$(".siac-cl-row div").first().text());' style='margin-right: 15px;'>Send to Field</div>
                                <div class='siac-btn siac-btn-dark' onclick='generateClozes();'>Generate</div>
                                </div>
                    `;"""

        else:
            s_html = "<br><center>Sorry, could not extract any sentences.</center>"
            btn_html = ""

        return """
                document.getElementById('siac-pdf-tooltip-results-area').innerHTML = `%s`;
                document.getElementById('siac-pdf-tooltip-top').innerHTML = `Found <b>%s</b> sentence(s) around selection: <br/><span style='color: lightgrey;'>(Click inside to edit, <i>Ctrl+Shift+C</i> to add new Clozes)</span>`;
                document.getElementById('siac-pdf-tooltip-searchbar').style.display = "none";
                %s
                """ % (s_html, len(sentences), btn_html)

    @js
    def notification(self, html, on_ok=None):
        if on_ok is None:
            on_ok = ""
        modal = f""" <div class="siac-modal-small dark" contenteditable="false" style="text-align:center; color: lightgrey;">
                        {html}
                        <br/> <br/>
                        <div class="siac-btn siac-btn-dark" onclick="$(this.parentNode).remove(); $('#siac-rm-greyout').hide(); {on_ok}">&nbsp; Ok &nbsp;</div>
                    </div> """
        return """$('#siac-pdf-tooltip').hide();
                $('.siac-modal-small').remove();
                $('#siac-rm-greyout').show();
                $('#siac-reading-modal-center').append('%s');""" % modal.replace("\n", "").replace("'", "\\'")

    @js
    def update_bottom_bar_positions(self, nid, new_index, queue_len):
        queue_readings_list = get_queue_head_display(nid).replace("`", "\\`")
        priority_str = get_priority_as_str(nid)
        return f"""
            document.getElementById('siac-queue-lbl').innerHTML = 'Priority: {priority_str}';
            $('#siac-queue-lbl').fadeIn('slow');
            $('.siac-queue-sched-btn:first').html('Priority');
            $('#siac-queue-readings-list').replaceWith(`{queue_readings_list}`);
        """

    @js
    def show_timer_elapsed_popup(self, nid):
        """
            Shows the little popup that is displayed when the timer in the reading modal finished.
        """
        read_today_count = get_read_today_count()
        added_today_count = utility.misc.count_cards_added_today()
        html = """
        <div style='margin: 0 0 10px 0;'>
            <div style='text-align: center; vertical-align: middle; line-height: 50px; font-weight: bold; font-size: 40px; color: #2496dc;'>
                &#10711;
            </div>
            <div style='text-align: center; vertical-align: middle; line-height: 50px; font-weight: bold; font-size: 20px;'>
                Time is up!
            </div>
        </div>
        <div style='margin: 10px 0 25px 0; text-align: center; color: lightgrey;'>
            Read <b>%s</b> %s today.<br>
            Added <b>%s</b> %s today.
        </div>
        <div style='text-align: center; margin-bottom: 8px;'>
            Start:
        </div>
        <div style='text-align: center;'>
            <div class='siac-btn siac-btn-dark' style='margin: 0 5px 0 5px;' onclick='this.parentNode.parentNode.style.display="none"; startTimer(5);'>&nbsp;5m&nbsp;</div>
            <div class='siac-btn siac-btn-dark' style='margin: 0 5px 0 5px;' onclick='this.parentNode.parentNode.style.display="none"; startTimer(15);'>&nbsp;15m&nbsp;</div>
            <div class='siac-btn siac-btn-dark' style='margin: 0 5px 0 5px;' onclick='this.parentNode.parentNode.style.display="none"; startTimer(30);'>&nbsp;30m&nbsp;</div>
            <div class='siac-btn siac-btn-dark' style='margin: 0 5px 0 5px;' onclick='this.parentNode.parentNode.style.display="none"; startTimer(60);'>&nbsp;60m&nbsp;</div>
        </div>
        <div style='text-align: center; margin-top: 20px;'>
            <div class='siac-btn siac-btn-dark' onclick='this.parentNode.parentNode.style.display="none";'>Don't Start</div>
        </div>
        """ % (read_today_count, "page" if read_today_count == 1 else "pages", added_today_count, "card" if added_today_count == 1 else "cards")
        return "$('#siac-timer-popup').html(`%s`); $('#siac-timer-popup').show();" % html


    @js
    def jump_to_last_read_page(self, nid):
        return """
            if (pagesRead && pagesRead.length) {
                pdfDisplayedCurrentPage = Math.max(...pagesRead);
                rerenderPDFPage(pdfDisplayedCurrentPage, false, true);
            }
        """
    @js
    def jump_to_first_unread_page(self, nid):
        return """
            if (pdfDisplayed) {
                for (var i = 1; i < pdfDisplayed.numPages + 1; i++) {
                    if (!pagesRead || pagesRead.indexOf(i) === -1) {
                        pdfDisplayedCurrentPage = i;
                        rerenderPDFPage(pdfDisplayedCurrentPage, false, true);
                        break;
                    }
                }
            }
        """

    #
    # highlights
    #

    def show_highlights_for_page(self, page):
        highlights = get_highlights(self.note_id, page)
        if highlights is not None and len(highlights) > 0:
            js = ""
            for rowid, nid, page, type, grouping, x0, y0, x1, y1, text, data, created in highlights:
                text = text.replace("`", "")
                js = f"{js},[{x0},{y0},{x1},{y1},{type},{rowid}, `{text}`]"
            js = js[1:]
            self._editor.web.eval("Highlighting.current = [%s]; Highlighting.displayHighlights();" % js)





class ReadingModalSidebar():
    def __init__(self):
        self._editor = None

        self.tab_displayed = "fields"
        # cache last results to display when the tab is reopened
        self.browse_tab_last_results = None
        self.pdfs_tab_last_results = None

        #
        # Pagination
        #
        self.page = 1
        self.last_results = None
        self.page_size = 100

    def set_editor(self, editor):
        self._editor = editor


    def print(self, results, stamp = "", query_set = []):
        self.last_results = results
        self.last_stamp = stamp
        self.last_query_set = query_set
        self.show_page(1)

    def show_page(self, page):
        self.page = page
        if self.last_results is not None:
            to_print = self.last_results[(page- 1) * self.page_size: page * self.page_size]
            if self.tab_displayed == "browse":
                self.browse_tab_last_results = (self.last_results, self.last_stamp, self.last_query_set)
                self._print_sidebar_search_results(to_print, self.last_stamp, self.last_query_set)
            elif self.tab_displayed == "pdfs":
                self.pdfs_tab_last_results = self.last_results
                self._print_sidebar_results_title_only(to_print)


    def show_fields_tab(self):
        if self.tab_displayed == "fields":
            return
        self.tab_displayed = "fields"
        self._editor.web.eval("""
            $('#siac-left-tab-browse,#siac-left-tab-pdfs').remove();
            document.getElementById("fields").style.display = 'block';
        """)


    def show_browse_tab(self):
        if self.tab_displayed == "browse":
            return
        self.tab_displayed = "browse"
        self._editor.web.eval(f"""
            document.getElementById("fields").style.display = 'none';
            $('#siac-left-tab-browse,#siac-left-tab-pdfs').remove();
            $(`
                <div id='siac-left-tab-browse' style='display: flex; flex-direction: column;'>
                    <div class='siac-pdf-main-color-border-bottom' style='flex: 0 auto; padding: 5px 0 5px 0; user-select: none;'>
                        <strong style='color: grey;'>Last: </strong>
                        <strong class='blue-hover' style='color: grey; margin-left: 10px;' onclick='pycmd("siac-pdf-sidebar-last-addon")'>Add-on</strong>
                        <strong class='blue-hover' style='color: grey; margin-left: 10px;' onclick='pycmd("siac-pdf-sidebar-last-anki")'>Anki</strong>
                    </div>
                    <div id='siac-left-tab-browse-results' style='flex: 1 1 auto; overflow-y: auto; padding: 0 5px 0 0; margin: 10px 0 5px 0;'>
                    </div>
                    <div style='flex: 0 auto; padding: 5px 0 5px 0;'>
                        <input type='text' style='width: 100%; box-sizing: border-box;' onkeyup='pdfLeftTabAnkiSearchKeyup(this.value, event);'/>
                    </div>
                </div>
            `).insertBefore('#siac-reading-modal-tabs-left');
        """)
        if self.browse_tab_last_results is not None:
            self.print(self.browse_tab_last_results[0], self.browse_tab_last_results[1], self.browse_tab_last_results[2])

    def show_pdfs_tab(self):
        if self.tab_displayed == "pdfs":
            return
        self.tab_displayed = "pdfs"
        self._editor.web.eval(f"""
            document.getElementById("fields").style.display = 'none';
            $('#siac-left-tab-browse,#siac-left-tab-pdfs').remove();
            $(`
                <div id='siac-left-tab-pdfs' style='display: flex; flex-direction: column;'>
                    <div class='siac-pdf-main-color-border-bottom' style='flex: 0 auto; padding: 5px 0 5px 0; user-select: none;'>
                        <strong class='blue-hover' style='color: grey; margin-left: 10px;' onclick='pycmd("siac-pdf-sidebar-pdfs-in-progress")'>In Progress</strong>
                        <strong class='blue-hover' style='color: grey; margin-left: 10px;' onclick='pycmd("siac-pdf-sidebar-pdfs-unread")'>Unread</strong>
                    </div>
                    <div id='siac-left-tab-browse-results' style='flex: 1 1 auto; overflow-y: auto; padding: 0 5px 0 0; margin: 10px 0 5px 0;'>
                    </div>
                    <div style='flex: 0 auto; padding: 5px 0 5px 0;'>
                        <input type='text' style='width: 100%; box-sizing: border-box;' onkeyup='pdfLeftTabPdfSearchKeyup(this.value, event);'/>
                    </div>
                </div>
            `).insertBefore('#siac-reading-modal-tabs-left');
        """)
        if self.pdfs_tab_last_results is not None:
            self.print(self.pdfs_tab_last_results)


    def _print_sidebar_search_results(self, results, stamp, query_set):
        """
            Print the results of the browse tab.
        """
        if results is not None and len(results) > 0:
            limit = get_config_value_or_default("pdfTooltipResultLimit", 50)
            html = self._sidebar_search_results(results[:limit], query_set)
            self._editor.web.eval("""
                document.getElementById('siac-left-tab-browse-results').innerHTML = `%s`;
                document.getElementById('siac-left-tab-browse-results').scrollTop = 0;
            """ % html)
        else:
            if query_set is None or len(query_set)  == 0:
                message = "Query was empty after cleaning."
            else:
                message = "Nothing found for query: <br/><br/><i>%s</i>" % (utility.text.trim_if_longer_than(" ".join(query_set), 200))
            self._editor.web.eval("""
                document.getElementById('siac-left-tab-browse-results').innerHTML = `%s`;
            """ % message)

    def _print_sidebar_results_title_only(self, results):
        """
            Print the results of the pdfs tab.
        """
        if results is None or len(results) == 0:
            return
        html = ""
        limit = get_config_value_or_default("pdfTooltipResultLimit", 50)
        for note in results[:limit]:
            should_show_loader = 'document.getElementById("siac-reading-modal-center").innerHTML = ""; showLoader(\"siac-reading-modal-center\", \"Loading Note...\");' if note.is_pdf() else ""
            html = f"{html}<div class='siac-note-title-only' onclick='if (!pdfLoading) {{{should_show_loader}  destroyPDF(); noteLoading = true; greyoutBottom(); pycmd(\"siac-read-user-note {note.id}\"); hideQueueInfobox();}}'>{note.get_title()}</div>"
        html = html.replace("`", "\\`")
        self._editor.web.eval(f"document.getElementById('siac-left-tab-browse-results').innerHTML = `{html}`;")



    def _sidebar_search_results(self, db_list, query_set):
        html = ""
        epochTime = int(time.time() * 1000)
        timeDiffString = ""
        newNote = ""
        lastNote = ""
        nids = [r.id for r in db_list]
        show_ret = get_config_value_or_default("showRetentionScores", True)
        fields_to_hide_in_results = get_config_value_or_default("fieldsToHideInResults", {})
        remove_divs = get_config_value_or_default("removeDivsFromOutput", False)
        if show_ret:
            retsByNid = getRetentions(nids)
        ret = 0
        highlighting = get_config_value_or_default("highlighting", True)

        for counter, res in enumerate(db_list):
            ret = retsByNid[int(res.id)] if show_ret and int(res.id) in retsByNid else None
            if ret is not None:
                retMark = "background: %s; color: black;" % (utility.misc._retToColor(ret))
                retInfo = """<div class='retMark' style='%s'>%s</div>
                                """ % (retMark, int(ret))
            else:
                retInfo = ""

            lastNote = newNote
            text = res.get_content()

            # hide fields that should not be shown
            if str(res.mid) in fields_to_hide_in_results:
                text = "\u001f".join([spl for i, spl in enumerate(text.split("\u001f")) if i not in fields_to_hide_in_results[str(res.mid)]])

            #remove <div> tags if set in config
            if remove_divs and res.note_type != "user":
                text = utility.text.remove_divs(text)

            if highlighting and query_set is not None:
                text = utility.text.mark_highlights(text, query_set)

            text = utility.text.cleanFieldSeparators(text).replace("\\", "\\\\").replace("`", "\\`").replace("$", "&#36;")
            text = utility.text.try_hide_image_occlusion(text)
            #try to put fields that consist of a single image in their own line
            text = utility.text.newline_before_images(text)
            template = noteTemplateSimple if res.note_type == "index" else noteTemplateUserNoteSimple
            newNote = template.format(
                counter=counter+1,
                nid=res.id,
                edited="",
                mouseup="",
                text=text,
                ret=retInfo,
                tags=utility.tags.build_tag_string(res.tags, False, False, maxLength = 25, maxCount = 2),
                creation="")
            html += newNote
        return html