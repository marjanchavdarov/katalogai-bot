document.getElementById("fileInput").addEventListener("change", function() {
  var f = this.files[0];
  if (f) { document.getElementById("log").textContent = "File: " + f.name; }
});

function startUpload() {
  var fi = document.getElementById("fileInput");
  var store = document.getElementById("storeName").value.trim();
  var vf = document.getElementById("validFrom").value.trim();
  var vu = document.getElementById("validUntil").value.trim();
  if (!fi.files[0]) { alert("Select a PDF file!"); return; }
  if (!store) { alert("Enter store name!"); return; }
  if (!vf) { alert("Enter valid from date!"); return; }
  if (!vu) {
    var d = new Date(vf);
    d.setDate(d.getDate() + 14);
    vu = d.toISOString().split("T")[0];
  }
  var btn = document.getElementById("btn");
  btn.disabled = true;
  btn.textContent = "Processing...";
  var log = document.getElementById("log");
  log.textContent = "Starting...\n";
  var fd = new FormData();
  fd.append("file", fi.files[0]);
  fd.append("store", store);
  fd.append("valid_from", vf);
  fd.append("valid_until", vu);
  fetch("/upload", { method: "POST", body: fd }).then(function(resp) {
    var reader = resp.body.getReader();
    var decoder = new TextDecoder();
    var buffer = "";
    function read() {
      reader.read().then(function(result) {
        if (result.done) return;
        buffer += decoder.decode(result.value, { stream: true });
        var lines = buffer.split("\n");
        buffer = lines.pop();
        for (var i = 0; i < lines.length; i++) {
          var line = lines[i].trim();
          if (!line) continue;
          try {
            var data = JSON.parse(line);
            if (data.type === "start") {
              log.textContent += "Pages: " + data.pages + "\n";
            } else if (data.type === "page") {
              log.textContent += "Page " + data.page + "/" + data.total_pages + ": " + data.products_found + " products\n";
              log.scrollTop = log.scrollHeight;
            } else if (data.type === "done") {
              log.textContent += "\nDONE! " + data.products + " products saved!\n";
              btn.textContent = "Process Another";
              btn.disabled = false;
            } else if (data.type === "error") {
              log.textContent += "ERROR: " + data.message + "\n";
              btn.disabled = false;
              btn.textContent = "Try Again";
            }
          } catch(e) {}
        }
        read();
      });
    }
    read();
  }).catch(function(err) {
    log.textContent += "ERROR: " + err.message + "\n";
    btn.disabled = false;
    btn.textContent = "Try Again";
  });
}
