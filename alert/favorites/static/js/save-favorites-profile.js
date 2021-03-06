$(document).ready(function() {
    $('#save-favorite-notes-field').NobleCount('#characters-remaining',{
        // set up the char counter
        //on_negative: 'errortext',
        on_negative: function(t_obj, char_area, c_settings, char_rem){
            $('#characters-remaining').addClass("errortext");
            $('#saveFavorite').attr('disabled', 'disabled');
        },
        on_positive: function(t_obj, char_area, c_settings, char_rem){
            $('#characters-remaining').removeClass("errortext");
            $('#saveFavorite').removeAttr('disabled');
        },
        max_chars: '500'
    });
    $("#save-favorite-delete").click(function() {
        // Send a post that deletes the favorite from the DB, and if successful
        // remove the notes and tags from the sidebar, and toggle the star icon
        // to be blanked out.
        var csrf   = $("input[name=csrfmiddlewaretoken]").val();
        var doc_id = $("input#id_doc_id").val();
        var dataString = 'csrf=' + csrf + '&doc_id=' + doc_id + "&message=True";
        $.ajax({
            type: "POST",
            url: "/favorite/delete/",
            data: dataString,
            success: function(){
                window.location = '/profile/favorites/';
            }
        });
        return false;
    });
});


//This is from https://docs.djangoproject.com/en/dev/ref/contrib/csrf/#ajax
//Makes Django's anti-CSRF work.
$(document).ajaxSend(function(event, xhr, settings) {
 function getCookie(name) {
     var cookieValue = null;
     if (document.cookie && document.cookie != '') {
         var cookies = document.cookie.split(';');
         for (var i = 0; i < cookies.length; i++) {
             var cookie = jQuery.trim(cookies[i]);
             // Does this cookie string begin with the name we want?
             if (cookie.substring(0, name.length + 1) == (name + '=')) {
                 cookieValue = decodeURIComponent(cookie.substring(name.length + 1));
                 break;
             }
         }
     }
     return cookieValue;
 }
 function sameOrigin(url) {
     // url could be relative or scheme relative or absolute
     var host = document.location.host; // host + port
     var protocol = document.location.protocol;
     var sr_origin = '//' + host;
     var origin = protocol + sr_origin;
     // Allow absolute or scheme relative URLs to same origin
     return (url == origin || url.slice(0, origin.length + 1) == origin + '/') ||
         (url == sr_origin || url.slice(0, sr_origin.length + 1) == sr_origin + '/') ||
         // or any other URL that isn't scheme relative or absolute i.e relative.
         !(/^(\/\/|http:|https:).*/.test(url));
 }
 function safeMethod(method) {
     return (/^(GET|HEAD|OPTIONS|TRACE)$/.test(method));
 }

 if (!safeMethod(settings.type) && sameOrigin(settings.url)) {
     xhr.setRequestHeader("X-CSRFToken", getCookie('csrftoken'));
 }
});

